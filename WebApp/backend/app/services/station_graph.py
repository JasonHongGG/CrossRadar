from __future__ import annotations

import json
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.models.crossing import ConfidenceLevel, GeoPoint
from backend.app.services.rail_path import RailPathService
from backend.app.utils import haversine_meters, normalize_text, point_ratio_between_stations, project_point_onto_station_line


STATION_NAME_ALIASES = {
    "中州": "中洲",
    "蘇澳新站": "蘇澳新",
    "侯硐": "猴硐",
    "內彎": "內灣",
    "車程": "車埕",
    "安通": "東里",
    "鳳鳴火車站": "鳳鳴",
}

OSM_PATH_MAX_DISTANCE_MULTIPLIER = 2.5
OSM_PATH_MAX_DISTANCE_METERS = 20_000.0
OSM_PATH_GEOMETRY_DELTA_THRESHOLD = 0.35
OSM_PATH_GEOMETRY_DISTANCE_MULTIPLIER = 1.8
OSM_PATH_GEOMETRY_MIN_DISTANCE_METERS = 8_000.0


class StationGraphService:
    def __init__(
        self,
        tdx_client: TdxTraClient,
        rail_path_service: RailPathService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.tdx_client = tdx_client
        self.rail_path_service = rail_path_service
        self._stations: list[dict[str, Any]] | None = None
        self._station_lookup: dict[str, dict[str, Any]] | None = None
        self._station_lookup_by_id: dict[str, dict[str, Any]] | None = None
        self._station_reference_by_id: dict[str, dict[str, Any]] | None = None
        self._station_reference_by_name: dict[str, dict[str, Any]] | None = None

    async def _get_stations(self) -> list[dict[str, Any]]:
        if self._stations is not None:
            return self._stations

        stations = list(await self.tdx_client.get_stations())
        stations.extend(self._load_supplemental_stations())
        reference_by_id, reference_by_name = self._load_station_reference_lookup()
        self._stations = [
            self._merge_station_reference(station, reference_by_id, reference_by_name)
            for station in stations
        ]
        return self._stations

    async def get_station_lookup(self) -> dict[str, dict[str, Any]]:
        if self._station_lookup is not None:
            return self._station_lookup

        stations = await self._get_stations()
        lookup: dict[str, dict[str, Any]] = {}
        lookup_by_id: dict[str, dict[str, Any]] = {}
        for station in stations:
            name = station.get("StationName", {}).get("Zh_tw")
            key = normalize_text(name)
            if key and key not in lookup:
                lookup[key] = station
            station_id = station.get("StationID")
            if station_id:
                lookup_by_id[str(station_id)] = station
        self._station_lookup = lookup
        self._station_lookup_by_id = lookup_by_id
        return lookup

    async def get_station_lookup_by_id(self) -> dict[str, dict[str, Any]]:
        if self._station_lookup_by_id is not None:
            return self._station_lookup_by_id

        await self.get_station_lookup()
        return self._station_lookup_by_id or {}

    async def resolve_station(self, station_name: str | None) -> dict[str, Any] | None:
        if not station_name:
            return None
        lookup = await self.get_station_lookup()
        for candidate in self._candidate_station_keys(station_name):
            station = lookup.get(candidate)
            if station is not None:
                return station
        return None

    async def list_station_summaries(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        stations = await self._get_stations()
        summaries: list[dict[str, Any]] = []
        seen_station_ids: set[str] = set()

        for station in stations:
            station_id = str(station.get("StationID") or "").strip()
            if not station_id or station_id in seen_station_ids:
                continue

            position = station.get("StationPosition") or {}
            lat = position.get("PositionLat")
            lon = position.get("PositionLon")
            if lat is None or lon is None:
                continue

            seen_station_ids.add(station_id)
            uk_values = [str(value).strip() for value in station.get("UK") or [] if str(value).strip()]
            uk_primary = str(station.get("UK_primary") or "").strip() or (uk_values[0] if uk_values else None)
            summaries.append(
                {
                    "station_id": station_id,
                    "name": station.get("StationName", {}).get("Zh_tw"),
                    "position": {
                        "PositionLat": float(lat),
                        "PositionLon": float(lon),
                    },
                    "uk_values": uk_values,
                    "uk_primary": uk_primary,
                }
            )

        summaries.sort(key=lambda station: normalize_text(station.get("name")) or station["station_id"])
        if limit is not None:
            return summaries[:limit]
        return summaries

    def _load_supplemental_stations(self) -> list[dict[str, Any]]:
        path = self.settings.supplemental_stations_json_path
        if not path.exists():
            return []

        payload = json.loads(path.read_text(encoding="utf-8"))
        supplemental: list[dict[str, Any]] = []
        for item in payload.get("stations", []):
            name = str(item.get("name") or "").strip()
            station_id = str(item.get("station_id") or "").strip()
            position = item.get("position") or {}
            lat = position.get("PositionLat")
            lon = position.get("PositionLon")
            if lat is None:
                lat = item.get("lat")
            if lon is None:
                lon = item.get("lon")
            if not name or not station_id or lat is None or lon is None:
                continue

            supplemental.append(
                {
                    "StationID": station_id,
                    "StationName": {"Zh_tw": name},
                    "StationPosition": {
                        "PositionLat": float(lat),
                        "PositionLon": float(lon),
                    },
                    "Supplemental": True,
                    "SupplementalNote": item.get("note"),
                }
            )

        return supplemental

    def _load_station_reference_lookup(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        if self._station_reference_by_id is not None and self._station_reference_by_name is not None:
            return self._station_reference_by_id, self._station_reference_by_name

        path = self.settings.stations_official_uk_json_path
        if not path.exists():
            self._station_reference_by_id = {}
            self._station_reference_by_name = {}
            return self._station_reference_by_id, self._station_reference_by_name

        payload = json.loads(path.read_text(encoding="utf-8"))
        reference_by_id: dict[str, dict[str, Any]] = {}
        reference_by_name: dict[str, dict[str, Any]] = {}

        for raw_station in payload.get("stations", []):
            station_code = str(raw_station.get("stationCode") or "").strip()
            station_name = str(raw_station.get("stationName") or raw_station.get("name") or "").strip()
            uk_values = [str(value).strip() for value in raw_station.get("UK") or [] if str(value).strip()]
            uk_primary = str(raw_station.get("UK_primary") or "").strip() or (uk_values[0] if uk_values else None)
            if not station_code and not station_name:
                continue

            reference = {
                "stationCode": station_code,
                "stationName": station_name,
                "UK": uk_values,
                "UK_primary": uk_primary,
            }

            if station_code:
                reference_by_id[station_code] = reference

            normalized_name = normalize_text(station_name)
            if normalized_name and normalized_name not in reference_by_name:
                reference_by_name[normalized_name] = reference

        self._station_reference_by_id = reference_by_id
        self._station_reference_by_name = reference_by_name
        return reference_by_id, reference_by_name

    def _merge_station_reference(
        self,
        station: dict[str, Any],
        reference_by_id: dict[str, dict[str, Any]],
        reference_by_name: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        reference: dict[str, Any] | None = None
        station_id = str(station.get("StationID") or "").strip()
        if station_id:
            reference = reference_by_id.get(station_id)

        if reference is None:
            station_name = station.get("StationName", {}).get("Zh_tw")
            for candidate in self._candidate_station_keys(str(station_name or "")):
                reference = reference_by_name.get(candidate)
                if reference is not None:
                    break

        if reference is None:
            return station

        merged = dict(station)
        if reference.get("UK"):
            merged["UK"] = list(reference["UK"])
        if reference.get("UK_primary"):
            merged["UK_primary"] = reference["UK_primary"]
        return merged

    def _candidate_station_keys(self, station_name: str) -> list[str]:
        normalized = normalize_text(station_name)
        if not normalized:
            return []

        candidates = [normalized]
        alias = STATION_NAME_ALIASES.get(normalized)
        if alias:
            candidates.append(normalize_text(alias))
        if normalized.endswith("站"):
            candidates.append(normalized[:-1])

        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        return deduped

    async def enrich_crossing_properties(self, properties: dict[str, Any]) -> dict[str, Any]:
        station_a = await self.resolve_station(properties.get("station_a_name"))
        station_b = await self.resolve_station(properties.get("station_b_name"))

        enriched = dict(properties)
        if station_a:
            enriched["station_a_id"] = station_a.get("StationID")
            enriched["station_a_position"] = station_a.get("StationPosition")
            enriched["station_a_uk_values"] = [str(value).strip() for value in station_a.get("UK") or [] if str(value).strip()]
            enriched["station_a_uk_primary"] = str(station_a.get("UK_primary") or "").strip() or None
        if station_b:
            enriched["station_b_id"] = station_b.get("StationID")
            enriched["station_b_position"] = station_b.get("StationPosition")
            enriched["station_b_uk_values"] = [str(value).strip() for value in station_b.get("UK") or [] if str(value).strip()]
            enriched["station_b_uk_primary"] = str(station_b.get("UK_primary") or "").strip() or None
        if enriched.get("station_a_uk_primary") or enriched.get("station_b_uk_primary"):
            enriched["station_uk_reference_note"] = "車站 UK 為推估參考值，非精準量測。"

        if station_a and station_b:
            geometry = properties.get("geometry")
            point = GeoPoint.model_validate(geometry) if geometry and isinstance(geometry, dict) else None
            pos_a = station_a.get("StationPosition", {})
            pos_b = station_b.get("StationPosition", {})

            official_ratio = self._official_segment_ratio(properties)
            if official_ratio is not None:
                enriched["official_segment_ratio"] = official_ratio

            geometry_ratio = None
            if point is not None:
                geometry_ratio = point_ratio_between_stations(
                    pos_a.get("PositionLon"),
                    pos_a.get("PositionLat"),
                    pos_b.get("PositionLon"),
                    pos_b.get("PositionLat"),
                    point.lon,
                    point.lat,
                )
                enriched["geometry_segment_ratio"] = geometry_ratio

            path_ratio = None
            path_rejection_note = None
            if point is not None and self.rail_path_service is not None:
                path_result = self.rail_path_service.compute_segment_ratio(
                    station_a_position=pos_a,
                    station_b_position=pos_b,
                    crossing_point=point,
                    crossing_way_ids=properties.get("osm_rail_way_ids") or None,
                )
                if path_result is not None:
                    enriched["path_segment_ratio"] = path_result.ratio
                    path_assessment = self._assess_path_plausibility(
                        station_a_position=pos_a,
                        station_b_position=pos_b,
                        path_ratio=path_result.ratio,
                        geometry_ratio=geometry_ratio,
                        distance_from_station_a_meters=path_result.distance_from_station_a_meters,
                        distance_to_station_b_meters=path_result.distance_to_station_b_meters,
                    )
                    if path_assessment["plausible"]:
                        path_ratio = path_result.ratio
                    else:
                        path_rejection_note = path_assessment["note"]

            ratio, ratio_source, confidence, confidence_reason = self._select_segment_ratio(
                official_ratio=official_ratio,
                path_ratio=path_ratio,
                geometry_ratio=geometry_ratio,
                path_rejection_note=path_rejection_note,
                properties=properties,
            )
            enriched["segment_ratio"] = ratio
            enriched["ratio_source"] = ratio_source
            enriched["segment_confidence"] = confidence
            enriched["segment_confidence_reason"] = confidence_reason

        return enriched

    async def explain_crossing_properties(self, properties: dict[str, Any]) -> dict[str, Any]:
        station_a = await self.resolve_station(properties.get("station_a_name"))
        station_b = await self.resolve_station(properties.get("station_b_name"))
        enriched = await self.enrich_crossing_properties(properties)

        point = None
        geometry = properties.get("geometry")
        if geometry and isinstance(geometry, dict):
            point = GeoPoint.model_validate(geometry)

        geometry_projection = self._build_geometry_projection(point, station_a, station_b)
        path_explanation = self._build_path_explanation(
            point,
            station_a,
            station_b,
            properties,
            geometry_projection.get("value") if geometry_projection.get("available") else None,
        )

        return {
            "crossing": {
                "crossing_id": properties.get("crossing_id"),
                "name": properties.get("name"),
                "line": properties.get("line"),
                "county": properties.get("county"),
                "km_marker": properties.get("km_marker"),
                "km_value_meters": properties.get("km_value_meters"),
                "station_pair_text": properties.get("station_pair_text"),
                "query_station_pair_text": properties.get("query_station_pair_text"),
                "station_pair_source": properties.get("station_pair_source"),
                "matched_osm_id": properties.get("matched_osm_id"),
                "manual_mapping_applied": bool(properties.get("manual_mapping_applied")),
                "geometry": {"lon": point.lon, "lat": point.lat} if point is not None else None,
            },
            "stations": {
                "station_a": self._station_summary(station_a, properties.get("station_a_name")),
                "station_b": self._station_summary(station_b, properties.get("station_b_name")),
            },
            "ratios": {
                "selected": {
                    "value": enriched.get("segment_ratio"),
                    "source": enriched.get("ratio_source"),
                    "confidence": enriched.get("segment_confidence"),
                    "note": enriched.get("segment_confidence_reason"),
                },
                "osm_path": path_explanation,
            },
        }

    def resolve_runtime_ratio_for_station_pair(
        self,
        crossing: dict[str, Any],
        *,
        upstream_station_id: str | None,
        downstream_station_id: str | None,
        station_lookup_by_id: dict[str, dict[str, Any]] | None,
    ) -> tuple[float | None, str, ConfidenceLevel, str]:
        if not station_lookup_by_id:
            return (None, "unavailable", "low", "Station lookup is unavailable, so the stop-pair OSM ratio cannot be resolved.")
        if not upstream_station_id or not downstream_station_id:
            return (None, "unavailable", "low", "At least one stop in the train's actual station pair is missing, so the stop-pair OSM ratio cannot be resolved.")

        geometry = crossing.get("geometry") or {}
        if not isinstance(geometry, dict) or geometry.get("lon") is None or geometry.get("lat") is None:
            return (None, "unavailable", "low", "The crossing has no adopted geometry, so the stop-pair OSM ratio cannot be resolved.")
        if self.rail_path_service is None:
            return (None, "unavailable", "low", "The rail-path service is not configured, so the stop-pair OSM ratio cannot be resolved.")

        upstream_station = station_lookup_by_id.get(str(upstream_station_id)) or {}
        downstream_station = station_lookup_by_id.get(str(downstream_station_id)) or {}
        upstream_position = upstream_station.get("StationPosition") or {}
        downstream_position = downstream_station.get("StationPosition") or {}
        if (
            upstream_position.get("PositionLon") is None
            or upstream_position.get("PositionLat") is None
            or downstream_position.get("PositionLon") is None
            or downstream_position.get("PositionLat") is None
        ):
            return (None, "unavailable", "low", "At least one stop in the train's actual station pair has no usable coordinates, so the stop-pair OSM ratio cannot be resolved.")

        point = GeoPoint.model_validate(geometry)
        geometry_ratio = point_ratio_between_stations(
            upstream_position.get("PositionLon"),
            upstream_position.get("PositionLat"),
            downstream_position.get("PositionLon"),
            downstream_position.get("PositionLat"),
            point.lon,
            point.lat,
        )
        path_result = self.rail_path_service.compute_segment_ratio(
            station_a_position=upstream_position,
            station_b_position=downstream_position,
            crossing_point=point,
            crossing_way_ids=crossing.get("osm_rail_way_ids") or None,
        )
        if path_result is None:
            return (
                None,
                "unavailable",
                "low",
                "No usable connected OSM rail path was found for the train's actual previous/next stop pair.",
            )

        path_assessment = self._assess_path_plausibility(
            station_a_position=upstream_position,
            station_b_position=downstream_position,
            path_ratio=path_result.ratio,
            geometry_ratio=geometry_ratio,
            distance_from_station_a_meters=path_result.distance_from_station_a_meters,
            distance_to_station_b_meters=path_result.distance_to_station_b_meters,
        )
        if not path_assessment["plausible"]:
            return (
                None,
                "unavailable",
                "low",
                f"Rejected the stop-pair OSM ratio. {path_assessment['note']}",
            )

        return (
            path_result.ratio,
            "osm_path",
            "high",
            "Projected the crossing onto the train's actual previous/next stop pair using connected OSM rail geometry.",
        )

    def _station_span_meters(self, station_a_position: dict[str, Any], station_b_position: dict[str, Any]) -> float | None:
        station_a_lon = station_a_position.get("PositionLon")
        station_a_lat = station_a_position.get("PositionLat")
        station_b_lon = station_b_position.get("PositionLon")
        station_b_lat = station_b_position.get("PositionLat")
        if station_a_lon is None or station_a_lat is None or station_b_lon is None or station_b_lat is None:
            return None
        return haversine_meters(
            float(station_a_lat),
            float(station_a_lon),
            float(station_b_lat),
            float(station_b_lon),
        )

    def _assess_path_plausibility(
        self,
        *,
        station_a_position: dict[str, Any],
        station_b_position: dict[str, Any],
        path_ratio: float,
        geometry_ratio: float | None,
        distance_from_station_a_meters: float,
        distance_to_station_b_meters: float,
    ) -> dict[str, Any]:
        station_span_meters = self._station_span_meters(station_a_position, station_b_position)
        total_distance_meters = distance_from_station_a_meters + distance_to_station_b_meters
        distance_multiple = (
            total_distance_meters / station_span_meters
            if station_span_meters is not None and station_span_meters > 0
            else None
        )
        ratio_delta_from_projection = abs(path_ratio - geometry_ratio) if geometry_ratio is not None else None

        if distance_multiple is not None and total_distance_meters > max(station_span_meters * OSM_PATH_MAX_DISTANCE_MULTIPLIER, OSM_PATH_MAX_DISTANCE_METERS):
            return {
                "plausible": False,
                "reason": "path_exceeds_station_span",
                "note": (
                    f"Rejected the OSM path because the reconstructed rail distance ({total_distance_meters:.0f} m) is "
                    f"{distance_multiple:.1f}x the straight-line station span ({station_span_meters:.0f} m), which strongly suggests an OSM mismatch or a looping route."
                ),
                "station_span_meters": station_span_meters,
                "total_distance_meters": total_distance_meters,
                "distance_multiple": distance_multiple,
                "ratio_delta_from_projection": ratio_delta_from_projection,
            }

        if (
            ratio_delta_from_projection is not None
            and distance_multiple is not None
            and ratio_delta_from_projection >= OSM_PATH_GEOMETRY_DELTA_THRESHOLD
            and total_distance_meters > max(station_span_meters * OSM_PATH_GEOMETRY_DISTANCE_MULTIPLIER, OSM_PATH_GEOMETRY_MIN_DISTANCE_METERS)
        ):
            return {
                "plausible": False,
                "reason": "path_ratio_conflicts_with_geometry",
                "note": (
                    f"Rejected the OSM path because its ratio ({path_ratio:.3f}) diverges too far from the station-line projection "
                    f"({geometry_ratio:.3f}) while the reconstructed rail distance is already unusually long ({total_distance_meters:.0f} m)."
                ),
                "station_span_meters": station_span_meters,
                "total_distance_meters": total_distance_meters,
                "distance_multiple": distance_multiple,
                "ratio_delta_from_projection": ratio_delta_from_projection,
            }

        return {
            "plausible": True,
            "reason": "ok",
            "note": "Measured along connected OSM rail geometry from station A to the crossing and from the crossing to station B.",
            "station_span_meters": station_span_meters,
            "total_distance_meters": total_distance_meters,
            "distance_multiple": distance_multiple,
            "ratio_delta_from_projection": ratio_delta_from_projection,
        }

    def _official_segment_ratio(self, properties: dict[str, Any]) -> float | None:
        crossing_km = properties.get("km_value_meters")
        station_a_km = properties.get("station_a_route_km_meters")
        station_b_km = properties.get("station_b_route_km_meters")
        if crossing_km is None or station_a_km is None or station_b_km is None:
            return None
        span = float(station_b_km) - float(station_a_km)
        if span <= 0:
            return None
        ratio = (float(crossing_km) - float(station_a_km)) / span
        return max(0.0, min(1.0, ratio))

    def _station_summary(self, station: dict[str, Any] | None, label: str | None) -> dict[str, Any]:
        position = station.get("StationPosition") if station else None
        return {
            "label": label,
            "resolved": station is not None,
            "station_id": station.get("StationID") if station else None,
            "name": station.get("StationName", {}).get("Zh_tw") if station else None,
            "position": position,
        }

    def _build_geometry_projection(
        self,
        point: GeoPoint | None,
        station_a: dict[str, Any] | None,
        station_b: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if point is None:
            return {
                "available": False,
                "reason": "crossing_geometry_missing",
                "note": "The crossing has no adopted geometry, so straight-line projection cannot be shown.",
            }
        if station_a is None or station_b is None:
            return {
                "available": False,
                "reason": "station_pair_unresolved",
                "note": "At least one station in the crossing pair could not be resolved from the TDX station dataset.",
            }

        pos_a = station_a.get("StationPosition", {})
        pos_b = station_b.get("StationPosition", {})
        projection = project_point_onto_station_line(
            pos_a.get("PositionLon"),
            pos_a.get("PositionLat"),
            pos_b.get("PositionLon"),
            pos_b.get("PositionLat"),
            point.lon,
            point.lat,
        )
        return {
            "available": True,
            "reason": "ok",
            "note": "Projected the crossing onto the straight station-to-station line segment. This is a geometric fallback, not along-track distance.",
            "value": projection["ratio"],
            "offset_meters": projection["offset_meters"],
            "projected_point": {
                "lon": projection["projected_lon"],
                "lat": projection["projected_lat"],
            },
            "station_line": {
                "coordinates": [
                    [pos_a.get("PositionLon"), pos_a.get("PositionLat")],
                    [pos_b.get("PositionLon"), pos_b.get("PositionLat")],
                ]
            },
            "crossing_to_projection_line": {
                "coordinates": [
                    [point.lon, point.lat],
                    [projection["projected_lon"], projection["projected_lat"]],
                ]
            },
        }

    def _build_path_explanation(
        self,
        point: GeoPoint | None,
        station_a: dict[str, Any] | None,
        station_b: dict[str, Any] | None,
        properties: dict[str, Any],
        geometry_ratio: float | None,
    ) -> dict[str, Any]:
        if point is None:
            return {
                "available": False,
                "reason": "crossing_geometry_missing",
                "note": "The crossing has no adopted geometry, so OSM along-track measurement cannot be shown.",
            }
        if station_a is None or station_b is None:
            return {
                "available": False,
                "reason": "station_pair_unresolved",
                "note": "At least one station in the crossing pair could not be resolved from the TDX station dataset.",
            }
        if self.rail_path_service is None:
            return {
                "available": False,
                "reason": "rail_path_service_unavailable",
                "note": "The rail-path service is not configured, so OSM along-track measurement cannot be shown.",
            }
        explanation = self.rail_path_service.explain_segment_ratio(
            station_a_position=station_a.get("StationPosition", {}),
            station_b_position=station_b.get("StationPosition", {}),
            crossing_point=point,
            crossing_way_ids=properties.get("osm_rail_way_ids") or None,
        )
        if not explanation.get("available"):
            return explanation

        plausibility = self._assess_path_plausibility(
            station_a_position=station_a.get("StationPosition", {}),
            station_b_position=station_b.get("StationPosition", {}),
            path_ratio=float(explanation.get("ratio") or 0.0),
            geometry_ratio=geometry_ratio,
            distance_from_station_a_meters=float(explanation.get("distance_from_station_a_meters") or 0.0),
            distance_to_station_b_meters=float(explanation.get("distance_to_station_b_meters") or 0.0),
        )
        explanation.update(
            {
                "plausible": plausibility["plausible"],
                "selected_eligible": plausibility["plausible"],
                "station_span_meters": plausibility["station_span_meters"],
                "distance_multiple": plausibility["distance_multiple"],
                "ratio_delta_from_projection": plausibility["ratio_delta_from_projection"],
            }
        )
        if not plausibility["plausible"]:
            explanation["reason"] = plausibility["reason"]
            explanation["note"] = plausibility["note"]
        return explanation

    def _select_segment_ratio(
        self,
        *,
        official_ratio: float | None,
        path_ratio: float | None,
        geometry_ratio: float | None,
        path_rejection_note: str | None,
        properties: dict[str, Any],
    ) -> tuple[float | None, str, str, str]:
        ratio_override = properties.get("segment_ratio_override")
        override_source = str(properties.get("segment_ratio_override_source") or "").strip()
        if ratio_override is not None and override_source == "osm_path":
            override_confidence = properties.get("segment_ratio_override_confidence") or "high"
            override_note = properties.get("segment_ratio_override_note") or "Used an explicit OSM-derived ratio override for this crossing."
            return (
                float(ratio_override),
                "osm_path",
                str(override_confidence),
                str(override_note),
            )
        if path_ratio is not None:
            return (
                path_ratio,
                "osm_path",
                "high",
                "Used OSM rail-way geometry to measure along-track distance from station A to the crossing and from the crossing to station B.",
            )

        diagnostics: list[str] = []
        if ratio_override is not None and override_source and override_source != "osm_path":
            diagnostics.append(
                f"Ignored the explicit {override_source} ratio override because runtime ETA now accepts only OSM-derived path ratios."
            )
        if path_rejection_note:
            diagnostics.append(path_rejection_note)
        else:
            diagnostics.append("No accepted connected OSM rail path is currently available for this crossing.")
        if not diagnostics:
            diagnostics.append(
                "No usable OSM rail path was available for this crossing, so runtime ETA is unavailable until the curated data or path method is improved."
            )
        return (None, "unavailable", "low", " ".join(diagnostics))
