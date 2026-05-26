from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from backend.app.config import Settings, get_settings
from backend.app.models.crossing import GeoPoint
from backend.app.utils import haversine_meters


EXCLUDED_RAILWAY_TAGS = {
    "abandoned",
    "construction",
    "crossing",
    "level_crossing",
    "platform",
    "proposed",
    "razed",
    "station",
    "tram_stop",
}

PATH_DISTANCE_SCORE_WEIGHT = 0.25


@dataclass(frozen=True)
class RailPathRatio:
    ratio: float
    distance_from_station_a_meters: float
    distance_to_station_b_meters: float
    crossing_snap_distance_meters: float
    station_a_snap_distance_meters: float
    station_b_snap_distance_meters: float


@dataclass(frozen=True)
class _Segment:
    segment_id: int
    way_id: int
    start_node: int
    end_node: int
    length_meters: float


@dataclass(frozen=True)
class _SnappedPoint:
    segment_id: int
    way_id: int
    start_node: int
    end_node: int
    lon: float
    lat: float
    distance_from_start_meters: float
    distance_to_end_meters: float
    snap_distance_meters: float


@dataclass(frozen=True)
class _GraphData:
    segments: list[_Segment]
    segment_geometries: list[LineString]
    adjacency: dict[int, list[tuple[int, float]]]
    way_to_segments: dict[int, list[int]]
    segment_components: list[int]
    node_coordinates: list[tuple[float, float]]
    tree: STRtree


class RailPathService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def compute_segment_ratio(
        self,
        *,
        station_a_position: dict[str, float],
        station_b_position: dict[str, float],
        crossing_point: GeoPoint,
        crossing_way_ids: list[int] | None = None,
    ) -> RailPathRatio | None:
        graph = self._graph
        if graph is None:
            return None

        crossing = self._snap_point(
            crossing_point.lon,
            crossing_point.lat,
            candidate_way_ids=crossing_way_ids,
            max_snap_distance_meters=150.0,
        )
        if crossing is None:
            return None

        station_a, distance_from_station_a = self._select_station_snap(
            station_a_position.get("PositionLon"),
            station_a_position.get("PositionLat"),
            crossing,
            max_snap_distance_meters=1_500.0,
            measure_from_start=True,
        )
        station_b, distance_to_station_b = self._select_station_snap(
            station_b_position.get("PositionLon"),
            station_b_position.get("PositionLat"),
            crossing,
            max_snap_distance_meters=1_500.0,
            measure_from_start=False,
        )
        if station_a is None or station_b is None or distance_from_station_a is None or distance_to_station_b is None:
            return None

        total_distance = distance_from_station_a + distance_to_station_b
        if total_distance <= 0:
            return None

        ratio = max(0.0, min(1.0, distance_from_station_a / total_distance))
        return RailPathRatio(
            ratio=ratio,
            distance_from_station_a_meters=distance_from_station_a,
            distance_to_station_b_meters=distance_to_station_b,
            crossing_snap_distance_meters=crossing.snap_distance_meters,
            station_a_snap_distance_meters=station_a.snap_distance_meters,
            station_b_snap_distance_meters=station_b.snap_distance_meters,
        )

    def explain_segment_ratio(
        self,
        *,
        station_a_position: dict[str, float],
        station_b_position: dict[str, float],
        crossing_point: GeoPoint,
        crossing_way_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        graph = self._graph
        if graph is None:
            return {
                "available": False,
                "reason": "graph_unavailable",
                "note": "No cached OSM rail graph is available, so along-track measurement cannot be shown.",
            }

        crossing = self._snap_point(
            crossing_point.lon,
            crossing_point.lat,
            candidate_way_ids=crossing_way_ids,
            max_snap_distance_meters=150.0,
        )
        if crossing is None:
            return {
                "available": False,
                "reason": "crossing_cannot_snap",
                "note": "The crossing geometry could not snap onto an OSM rail segment within 150 meters.",
            }

        component_id = graph.segment_components[crossing.segment_id]
        station_a, distance_from_station_a = self._select_station_snap(
            station_a_position.get("PositionLon"),
            station_a_position.get("PositionLat"),
            crossing,
            max_snap_distance_meters=1_500.0,
            measure_from_start=True,
        )
        station_b, distance_to_station_b = self._select_station_snap(
            station_b_position.get("PositionLon"),
            station_b_position.get("PositionLat"),
            crossing,
            max_snap_distance_meters=1_500.0,
            measure_from_start=False,
        )

        payload: dict[str, Any] = {
            "available": False,
            "reason": None,
            "component_id": component_id,
            "crossing_snap": self._snapped_point_payload(crossing),
            "station_a_snap": self._snapped_point_payload(station_a),
            "station_b_snap": self._snapped_point_payload(station_b),
        }

        if station_a is None or distance_from_station_a is None:
            payload.update(
                {
                    "reason": "station_a_cannot_snap_same_component",
                    "note": "Station A could not snap onto the same connected OSM rail component as the crossing within 1,500 meters.",
                }
            )
            return payload

        if station_b is None or distance_to_station_b is None:
            payload.update(
                {
                    "reason": "station_b_cannot_snap_same_component",
                    "note": "Station B could not snap onto the same connected OSM rail component as the crossing within 1,500 meters.",
                }
            )
            return payload

        station_a_path = self._path_between_snapped(station_a, crossing)
        station_b_path = self._path_between_snapped(crossing, station_b)
        if station_a_path is None or station_b_path is None:
            payload.update(
                {
                    "reason": "path_geometry_unavailable",
                    "note": "A connected OSM rail path could not be reconstructed between the snapped station anchors and the crossing.",
                }
            )
            return payload

        total_distance = distance_from_station_a + distance_to_station_b
        if total_distance <= 0:
            payload.update(
                {
                    "reason": "invalid_total_distance",
                    "note": "The reconstructed along-track distance collapsed to zero, so no ratio can be derived.",
                }
            )
            return payload

        payload.update(
            {
                "available": True,
                "ratio": max(0.0, min(1.0, distance_from_station_a / total_distance)),
                "reason": "ok",
                "note": "Measured along connected OSM rail geometry from station A to the crossing and from the crossing to station B.",
                "distance_from_station_a_meters": distance_from_station_a,
                "distance_to_station_b_meters": distance_to_station_b,
                "total_distance_meters": total_distance,
                "crossing_snap_distance_meters": crossing.snap_distance_meters,
                "station_a_snap_distance_meters": station_a.snap_distance_meters,
                "station_b_snap_distance_meters": station_b.snap_distance_meters,
                "station_a_path": {
                    "distance_meters": station_a_path[0],
                    "coordinates": station_a_path[1],
                },
                "station_b_path": {
                    "distance_meters": station_b_path[0],
                    "coordinates": station_b_path[1],
                },
            }
        )
        return payload

    @cached_property
    def _graph(self) -> _GraphData | None:
        path = self.settings.osm_raw_json_path
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        elements = payload.get("elements", [])
        ways = [element for element in elements if self._is_rail_way(element)]
        if not ways:
            return None

        node_lookup: dict[tuple[float, float], int] = {}
        node_coordinates: list[tuple[float, float]] = []
        segments: list[_Segment] = []
        segment_geometries: list[LineString] = []
        adjacency: dict[int, list[tuple[int, float]]] = {}
        way_to_segments: dict[int, list[int]] = {}

        def get_node_id(lon: float, lat: float) -> int:
            key = (round(lon, 7), round(lat, 7))
            node_id = node_lookup.get(key)
            if node_id is None:
                node_id = len(node_coordinates)
                node_lookup[key] = node_id
                node_coordinates.append((lon, lat))
            return node_id

        for way in ways:
            way_id = int(way.get("id"))
            geometry = way.get("geometry") or []
            if len(geometry) < 2:
                continue
            for start, end in zip(geometry, geometry[1:]):
                start_lon = float(start.get("lon"))
                start_lat = float(start.get("lat"))
                end_lon = float(end.get("lon"))
                end_lat = float(end.get("lat"))
                length_meters = haversine_meters(start_lat, start_lon, end_lat, end_lon)
                if length_meters <= 0:
                    continue

                start_node = get_node_id(start_lon, start_lat)
                end_node = get_node_id(end_lon, end_lat)
                segment_id = len(segments)
                segments.append(
                    _Segment(
                        segment_id=segment_id,
                        way_id=way_id,
                        start_node=start_node,
                        end_node=end_node,
                        length_meters=length_meters,
                    )
                )
                segment_geometries.append(LineString([(start_lon, start_lat), (end_lon, end_lat)]))
                adjacency.setdefault(start_node, []).append((end_node, length_meters))
                adjacency.setdefault(end_node, []).append((start_node, length_meters))
                way_to_segments.setdefault(way_id, []).append(segment_id)

        if not segments:
            return None

        return _GraphData(
            segments=segments,
            segment_geometries=segment_geometries,
            adjacency=adjacency,
            way_to_segments=way_to_segments,
            segment_components=self._build_segment_components(segments, adjacency),
            node_coordinates=node_coordinates,
            tree=STRtree(segment_geometries),
        )

    def _build_segment_components(
        self,
        segments: list[_Segment],
        adjacency: dict[int, list[tuple[int, float]]],
    ) -> list[int]:
        component_by_node: dict[int, int] = {}
        current_component = 0
        for start_node in adjacency:
            if start_node in component_by_node:
                continue
            stack = [start_node]
            component_by_node[start_node] = current_component
            while stack:
                node_id = stack.pop()
                for neighbor_id, _ in adjacency.get(node_id, []):
                    if neighbor_id in component_by_node:
                        continue
                    component_by_node[neighbor_id] = current_component
                    stack.append(neighbor_id)
            current_component += 1
        return [component_by_node.get(segment.start_node, -1) for segment in segments]

    def _is_rail_way(self, element: dict) -> bool:
        if element.get("type") != "way":
            return False
        tags = element.get("tags", {}) or {}
        railway = str(tags.get("railway") or "").strip().casefold()
        if not railway or railway in EXCLUDED_RAILWAY_TAGS:
            return False
        return bool(element.get("geometry"))

    def _snap_point(
        self,
        lon: float | None,
        lat: float | None,
        *,
        candidate_way_ids: list[int] | None = None,
        max_snap_distance_meters: float,
    ) -> _SnappedPoint | None:
        graph = self._graph
        if graph is None or lon is None or lat is None:
            return None

        candidates = self._snap_point_candidates(
            lon,
            lat,
            candidate_way_ids=candidate_way_ids,
            max_snap_distance_meters=max_snap_distance_meters,
            max_candidates=1,
        )
        return candidates[0] if candidates else None

    def _snap_point_candidates(
        self,
        lon: float | None,
        lat: float | None,
        *,
        candidate_way_ids: list[int] | None = None,
        required_component: int | None = None,
        max_snap_distance_meters: float,
        max_candidates: int,
    ) -> list[_SnappedPoint]:
        graph = self._graph
        if graph is None or lon is None or lat is None:
            return []

        point = Point(float(lon), float(lat))
        candidate_segment_ids: list[int] = []
        if candidate_way_ids:
            for way_id in candidate_way_ids:
                candidate_segment_ids.extend(graph.way_to_segments.get(int(way_id), []))
        elif required_component is not None:
            candidate_segment_ids = [
                index for index, component in enumerate(graph.segment_components) if component == required_component
            ]

        if not candidate_segment_ids:
            candidate_segment_ids = sorted(
                range(len(graph.segment_geometries)),
                key=lambda index: graph.segment_geometries[index].distance(point),
            )[: max_candidates * 4]
        else:
            distance_by_segment: dict[int, float] = {}

            def segment_distance(index: int) -> float:
                distance = distance_by_segment.get(index)
                if distance is None:
                    distance = graph.segment_geometries[index].distance(point)
                    distance_by_segment[index] = distance
                return distance

            candidate_segment_ids = sorted(candidate_segment_ids, key=segment_distance)[: max_candidates * 8]

        candidates: list[_SnappedPoint] = []
        seen_segments: set[int] = set()
        for segment_id in candidate_segment_ids:
            if segment_id in seen_segments:
                continue
            seen_segments.add(segment_id)
            segment = graph.segments[segment_id]
            line = graph.segment_geometries[segment_id]
            normalized = max(0.0, min(1.0, float(line.project(point, normalized=True))))
            snapped = line.interpolate(normalized, normalized=True)
            snap_distance_meters = haversine_meters(float(lat), float(lon), snapped.y, snapped.x)
            if snap_distance_meters > max_snap_distance_meters:
                continue

            distance_from_start = segment.length_meters * normalized
            candidates.append(
                _SnappedPoint(
                    segment_id=segment.segment_id,
                    way_id=segment.way_id,
                    start_node=segment.start_node,
                    end_node=segment.end_node,
                    lon=float(snapped.x),
                    lat=float(snapped.y),
                    distance_from_start_meters=distance_from_start,
                    distance_to_end_meters=segment.length_meters - distance_from_start,
                    snap_distance_meters=snap_distance_meters,
                )
            )
            if len(candidates) >= max_candidates:
                break

        return candidates

    def _select_station_snap(
        self,
        lon: float | None,
        lat: float | None,
        crossing: _SnappedPoint,
        *,
        max_snap_distance_meters: float,
        measure_from_start: bool,
    ) -> tuple[_SnappedPoint | None, float | None]:
        graph = self._graph
        component = None
        if graph is not None:
            component = graph.segment_components[crossing.segment_id]
        candidates = self._snap_point_candidates(
            lon,
            lat,
            required_component=component,
            max_snap_distance_meters=max_snap_distance_meters,
            max_candidates=8,
        )
        best_candidate: _SnappedPoint | None = None
        best_distance: float | None = None
        best_score: float | None = None
        for candidate in candidates:
            distance = self._distance_between_snapped(candidate, crossing) if measure_from_start else self._distance_between_snapped(crossing, candidate)
            if distance is None:
                continue
            score = self._station_candidate_score(candidate.snap_distance_meters, distance)
            if best_score is None or score < best_score:
                best_candidate = candidate
                best_distance = distance
                best_score = score
        return (best_candidate, best_distance)

    def _station_candidate_score(self, snap_distance_meters: float, path_distance_meters: float) -> float:
        # Favor anchors that remain physically close to the station while still preferring a connected path.
        return snap_distance_meters + path_distance_meters * PATH_DISTANCE_SCORE_WEIGHT

    def _distance_between_snapped(self, start: _SnappedPoint, end: _SnappedPoint) -> float | None:
        best: float | None = None
        if start.segment_id == end.segment_id:
            best = abs(start.distance_from_start_meters - end.distance_from_start_meters)

        graph_distance = self._dijkstra(
            [
                (start.start_node, start.distance_from_start_meters),
                (start.end_node, start.distance_to_end_meters),
            ],
            {
                end.start_node: end.distance_from_start_meters,
                end.end_node: end.distance_to_end_meters,
            },
        )
        if graph_distance is None:
            return best
        if best is None:
            return graph_distance
        return min(best, graph_distance)

    def _path_between_snapped(self, start: _SnappedPoint, end: _SnappedPoint) -> tuple[float, list[list[float]]] | None:
        direct_distance: float | None = None
        direct_coordinates: list[list[float]] | None = None
        if start.segment_id == end.segment_id:
            direct_distance = abs(start.distance_from_start_meters - end.distance_from_start_meters)
            direct_coordinates = self._dedupe_coordinates(
                [
                    [start.lon, start.lat],
                    [end.lon, end.lat],
                ]
            )

        graph_result = self._dijkstra_path(
            [
                (start.start_node, start.distance_from_start_meters),
                (start.end_node, start.distance_to_end_meters),
            ],
            {
                end.start_node: end.distance_from_start_meters,
                end.end_node: end.distance_to_end_meters,
            },
        )
        if graph_result is None:
            if direct_distance is None or direct_coordinates is None:
                return None
            return direct_distance, direct_coordinates

        graph_distance, node_path = graph_result
        graph_coordinates = self._coordinates_for_node_path(start, node_path, end)
        if direct_distance is not None and direct_coordinates is not None and direct_distance <= graph_distance:
            return direct_distance, direct_coordinates
        return graph_distance, graph_coordinates

    def _coordinates_for_node_path(
        self,
        start: _SnappedPoint,
        node_path: list[int],
        end: _SnappedPoint,
    ) -> list[list[float]]:
        graph = self._graph
        if graph is None:
            return self._dedupe_coordinates([[start.lon, start.lat], [end.lon, end.lat]])

        coordinates: list[list[float]] = [[start.lon, start.lat]]
        for node_id in node_path:
            lon, lat = graph.node_coordinates[node_id]
            coordinates.append([lon, lat])
        coordinates.append([end.lon, end.lat])
        return self._dedupe_coordinates(coordinates)

    def _dedupe_coordinates(self, coordinates: list[list[float]]) -> list[list[float]]:
        deduped: list[list[float]] = []
        for coordinate in coordinates:
            if not deduped or deduped[-1] != coordinate:
                deduped.append(coordinate)
        return deduped

    def _snapped_point_payload(self, snapped: _SnappedPoint | None) -> dict[str, Any] | None:
        if snapped is None:
            return None
        graph = self._graph
        component_id = None
        if graph is not None:
            component_id = graph.segment_components[snapped.segment_id]
        return {
            "lon": snapped.lon,
            "lat": snapped.lat,
            "segment_id": snapped.segment_id,
            "way_id": snapped.way_id,
            "component_id": component_id,
            "snap_distance_meters": snapped.snap_distance_meters,
            "distance_from_start_meters": snapped.distance_from_start_meters,
            "distance_to_end_meters": snapped.distance_to_end_meters,
        }

    def _dijkstra_path(self, sources: list[tuple[int, float]], targets: dict[int, float]) -> tuple[float, list[int]] | None:
        graph = self._graph
        if graph is None:
            return None

        distances: dict[int, float] = {}
        previous: dict[int, int | None] = {}
        heap: list[tuple[float, int]] = []
        for node_id, distance in sources:
            current = distances.get(node_id)
            if current is None or distance < current:
                distances[node_id] = distance
                previous[node_id] = None
                heapq.heappush(heap, (distance, node_id))

        best_target_distance: float | None = None
        best_target_node: int | None = None
        while heap:
            distance, node_id = heapq.heappop(heap)
            if distance > distances.get(node_id, float("inf")):
                continue
            if best_target_distance is not None and distance >= best_target_distance:
                continue

            if node_id in targets:
                candidate = distance + targets[node_id]
                if best_target_distance is None or candidate < best_target_distance:
                    best_target_distance = candidate
                    best_target_node = node_id

            for neighbor_id, weight in graph.adjacency.get(node_id, []):
                candidate = distance + weight
                if candidate >= distances.get(neighbor_id, float("inf")):
                    continue
                distances[neighbor_id] = candidate
                previous[neighbor_id] = node_id
                heapq.heappush(heap, (candidate, neighbor_id))

        if best_target_distance is None or best_target_node is None:
            return None

        path_nodes: list[int] = []
        cursor: int | None = best_target_node
        while cursor is not None:
            path_nodes.append(cursor)
            cursor = previous.get(cursor)
        path_nodes.reverse()
        return best_target_distance, path_nodes

    def _dijkstra(self, sources: list[tuple[int, float]], targets: dict[int, float]) -> float | None:
        graph = self._graph
        if graph is None:
            return None

        distances: dict[int, float] = {}
        heap: list[tuple[float, int]] = []
        for node_id, distance in sources:
            current = distances.get(node_id)
            if current is None or distance < current:
                distances[node_id] = distance
                heapq.heappush(heap, (distance, node_id))

        best_target: float | None = None
        while heap:
            distance, node_id = heapq.heappop(heap)
            if distance > distances.get(node_id, float("inf")):
                continue
            if best_target is not None and distance >= best_target:
                continue

            if node_id in targets:
                candidate = distance + targets[node_id]
                if best_target is None or candidate < best_target:
                    best_target = candidate

            for neighbor_id, weight in graph.adjacency.get(node_id, []):
                candidate = distance + weight
                if candidate >= distances.get(neighbor_id, float("inf")):
                    continue
                distances[neighbor_id] = candidate
                heapq.heappush(heap, (candidate, neighbor_id))

        return best_target