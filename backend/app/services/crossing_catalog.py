from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.models.crossing import ConfidenceLevel, CrossingRecord, GeoPoint
from backend.app.services.crossing_scraper import TraOfficialCrossingScraper
from backend.app.services.osm_enricher import OsmEnricher
from backend.app.services.route_reference import RouteReferenceService
from backend.app.services.station_graph import (
    OSM_PATH_GEOMETRY_DELTA_THRESHOLD,
    OSM_PATH_GEOMETRY_DISTANCE_MULTIPLIER,
    OSM_PATH_GEOMETRY_MIN_DISTANCE_METERS,
    OSM_PATH_MAX_DISTANCE_METERS,
    OSM_PATH_MAX_DISTANCE_MULTIPLIER,
    StationGraphService,
)
from backend.app.utils import haversine_meters, normalize_text, point_ratio_between_stations, project_point_onto_station_line


OSM_STATION_CORRIDOR_MAX_OFFSET_MULTIPLIER = 2.0
OSM_STATION_CORRIDOR_MAX_OFFSET_METERS = 10_000.0
OSM_LOCAL_SIBLING_RADIUS_METERS = 20.0


class CrossingCatalogService:
    def __init__(
        self,
        scraper: TraOfficialCrossingScraper,
        osm_enricher: OsmEnricher,
        settings: Settings | None = None,
        route_reference_service: RouteReferenceService | None = None,
        station_graph_service: StationGraphService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.scraper = scraper
        self.osm_enricher = osm_enricher
        self.route_reference_service = route_reference_service or RouteReferenceService(self.settings)
        self.station_graph_service = station_graph_service

    async def refresh(self, *, force_refresh: bool = False) -> dict[str, Any]:
        official_records = await self.scraper.scrape_all(force_refresh=force_refresh)
        osm_geojson = await self.osm_enricher.build_geojson(force_refresh=force_refresh)
        route_referenced_records = [self.route_reference_service.apply(record.model_copy(deep=True)) for record in official_records]
        station_context_lookup = await self._build_station_context_lookup(route_referenced_records)
        full_dataset = self._build_curated_geojson(official_records, osm_geojson, station_context_lookup=station_context_lookup)
        active_dataset = self._build_active_geojson(full_dataset)
        official_tainan_dataset = self._build_official_county_subset(official_records, county="臺南市")
        curated_tainan_dataset = self._build_geojson_county_subset(active_dataset, county="臺南市")

        self.settings.full_crossings_geojson_path.write_text(
            json.dumps(full_dataset, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.settings.curated_crossings_geojson_path.write_text(
            json.dumps(active_dataset, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.settings.official_tainan_crossings_json_path.write_text(
            json.dumps(official_tainan_dataset, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.settings.curated_tainan_crossings_geojson_path.write_text(
            json.dumps(curated_tainan_dataset, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return active_dataset

    async def load(self) -> dict[str, Any]:
        if self._is_crossing_cache_stale():
            return await self.refresh(force_refresh=False)
        return json.loads(self.settings.curated_crossings_geojson_path.read_text(encoding="utf-8"))

    async def load_full(self) -> dict[str, Any]:
        if self._is_crossing_cache_stale():
            await self.refresh(force_refresh=False)
        return json.loads(self.settings.full_crossings_geojson_path.read_text(encoding="utf-8"))

    def _is_crossing_cache_stale(self) -> bool:
        generated_paths = (
            self.settings.curated_crossings_geojson_path,
            self.settings.full_crossings_geojson_path,
            self.settings.official_tainan_crossings_json_path,
            self.settings.curated_tainan_crossings_geojson_path,
        )
        if any(not path.exists() for path in generated_paths):
            return True

        baseline_mtime = min(path.stat().st_mtime for path in generated_paths)
        dependencies = (
            self.settings.manual_mappings_json_path,
            self.settings.official_crossings_json_path,
            self.settings.osm_geojson_path,
            self.settings.route_reference_json_path,
        )
        return any(self._path_is_newer(path, baseline_mtime) for path in dependencies)

    def _path_is_newer(self, path: Path, baseline_mtime: float) -> bool:
        return path.exists() and path.stat().st_mtime > baseline_mtime

    async def list_crossings(
        self,
        *,
        county: str | None = None,
        confidence: str | None = None,
        mapped_only: bool = True,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        dataset = await self.load()
        items = dataset.get("features", [])
        results: list[dict[str, Any]] = []
        for feature in items:
            properties = feature.get("properties", {})
            if county and properties.get("county") != county:
                continue
            if confidence and properties.get("geolocation_confidence") != confidence:
                continue
            if mapped_only and feature.get("geometry") is None:
                continue
            results.append(feature)
            if len(results) >= limit:
                break
        return results

    async def get_crossing(self, crossing_id: str) -> dict[str, Any] | None:
        dataset = await self.load()
        for feature in dataset.get("features", []):
            if feature.get("id") == crossing_id or feature.get("properties", {}).get("crossing_id") == crossing_id:
                return feature
        return None

    def _build_active_geojson(self, dataset: dict[str, Any]) -> dict[str, Any]:
        all_features = dataset.get("features", [])
        active_features = [feature for feature in all_features if feature.get("geometry") is not None]
        metadata = {
            **dataset.get("metadata", {}),
            "source": "official+osm_active",
            "selection_rule": "Only crossings with an adopted geometry are included; unresolved or stale location records are excluded from the runtime dataset.",
            "feature_count": len(active_features),
            "excluded_feature_count": max(len(all_features) - len(active_features), 0),
            "full_feature_count": len(all_features),
            "full_dataset_path": str(self.settings.full_crossings_geojson_path),
        }
        return {
            "type": "FeatureCollection",
            "metadata": metadata,
            "features": active_features,
        }

    def _build_geojson_county_subset(self, dataset: dict[str, Any], *, county: str) -> dict[str, Any]:
        features = [
            feature
            for feature in dataset.get("features", [])
            if normalize_text(feature.get("properties", {}).get("county")) == normalize_text(county)
        ]
        metadata = {
            **dataset.get("metadata", {}),
            "scope_county": county,
            "feature_count": len(features),
            "source_feature_count": len(dataset.get("features", [])),
        }
        return {
            "type": "FeatureCollection",
            "metadata": metadata,
            "features": features,
        }

    def _build_official_county_subset(self, official_records: list[CrossingRecord], *, county: str) -> dict[str, Any]:
        records = [
            record.model_dump()
            for record in official_records
            if normalize_text(record.county) == normalize_text(county)
        ]
        return {
            "metadata": {
                "source": str(self.settings.official_crossings_json_path),
                "scope_county": county,
                "count": len(records),
                "full_count": len(official_records),
            },
            "crossings": records,
        }

    def _build_curated_geojson(
        self,
        official_records: list[CrossingRecord],
        osm_geojson: dict[str, Any],
        *,
        station_context_lookup: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        osm_features = osm_geojson.get("features", [])
        manual_mapping_lookup = self._load_manual_mapping_lookup()
        route_reference_metadata = self.route_reference_service.metadata()
        features: list[dict[str, Any]] = []
        mapped_count = 0
        authoritative_pair_count = 0

        for official in official_records:
            updated = self.route_reference_service.apply(official.model_copy(deep=True))
            station_context = (station_context_lookup or {}).get(updated.crossing_id)
            if updated.authoritative_reference_applied:
                authoritative_pair_count += 1

            manual_mapping = manual_mapping_lookup.get(official.crossing_id)
            manual_geometry = self._manual_geometry_from_mapping(manual_mapping)
            if manual_mapping is not None:
                matched_feature = self._find_osm_feature_by_id(osm_features, manual_mapping.get("osm_id"))
                if matched_feature is not None:
                    score = 100.0
                    match_method = "manual_override"
                    confidence = "high"
                elif manual_geometry is not None:
                    matched_feature = None
                    score = 100.0
                    match_method = "manual_coordinate_override"
                    confidence = "high"
                else:
                    matched_feature, score, match_method, confidence = self._match_official_to_osm(updated, osm_features, station_context=station_context)
            else:
                matched_feature, score, match_method, confidence = self._match_official_to_osm(updated, osm_features, station_context=station_context)
                matched_feature, score, match_method = self._prefer_plausible_local_osm_candidate(
                    updated,
                    matched_feature,
                    score,
                    match_method,
                    osm_features,
                    station_context=station_context,
                )

            updated.match_score = score
            updated.match_method = match_method
            updated.geolocation_confidence = confidence
            updated.manual_mapping_applied = manual_mapping is not None and (matched_feature is not None or manual_geometry is not None)

            if matched_feature is not None and confidence in ("high", "medium"):
                properties = matched_feature.get("properties", {})
                geometry = matched_feature.get("geometry", {})
                coordinates = geometry.get("coordinates") or [None, None]
                if coordinates[0] is not None and coordinates[1] is not None:
                    updated.geometry = GeoPoint(lat=coordinates[1], lon=coordinates[0])
                    updated.matched_osm_id = properties.get("osm_id")
                    updated.osm_road_names = properties.get("road_names", [])
                    updated.osm_rail_names = properties.get("rail_names", [])
                    updated.osm_rail_way_ids = properties.get("rail_way_ids", [])
                    updated.osm_tags = properties.get("tags", {})
                    if self._matched_geometry_is_plausible(updated, station_context=station_context):
                        mapped_count += 1
                    else:
                        self._clear_osm_match(updated)
            elif manual_geometry is not None and confidence in ("high", "medium"):
                updated.geometry = manual_geometry
                updated.matched_osm_id = None
                updated.osm_road_names = []
                updated.osm_rail_names = []
                updated.osm_rail_way_ids = []
                updated.osm_tags = {}
                if self._matched_geometry_is_plausible(updated, station_context=station_context):
                    mapped_count += 1
                else:
                    self._clear_osm_match(updated)

            features.append(updated.to_feature())

        return {
            "type": "FeatureCollection",
            "metadata": {
                "source": "official+osm",
                "official_count": len(official_records),
                "mapped_count": mapped_count,
                "authoritative_pair_count": authoritative_pair_count,
                "osm_feature_count": len(osm_features),
                "osm_raw_path": str(self.settings.osm_raw_json_path),
                "route_reference": route_reference_metadata,
            },
            "features": features,
        }

    async def _build_station_context_lookup(self, records: list[CrossingRecord]) -> dict[str, dict[str, Any]]:
        if self.station_graph_service is None:
            return {}

        lookup: dict[str, dict[str, Any]] = {}
        for record in records:
            station_context = await self._build_station_context(record)
            if station_context is not None:
                lookup[record.crossing_id] = station_context
        return lookup

    async def _build_station_context(self, record: CrossingRecord) -> dict[str, Any] | None:
        if self.station_graph_service is None:
            return None

        station_a = await self.station_graph_service.resolve_station(record.station_a_name)
        station_b = await self.station_graph_service.resolve_station(record.station_b_name)
        if station_a is None or station_b is None:
            return None

        station_a_position = station_a.get("StationPosition", {})
        station_b_position = station_b.get("StationPosition", {})
        station_a_lon = station_a_position.get("PositionLon")
        station_a_lat = station_a_position.get("PositionLat")
        station_b_lon = station_b_position.get("PositionLon")
        station_b_lat = station_b_position.get("PositionLat")
        if station_a_lon is None or station_a_lat is None or station_b_lon is None or station_b_lat is None:
            return None

        return {
            "station_a_position": station_a_position,
            "station_b_position": station_b_position,
            "station_span_meters": haversine_meters(
                float(station_a_lat),
                float(station_a_lon),
                float(station_b_lat),
                float(station_b_lon),
            ),
        }

    def _corridor_match_assessment(self, osm_feature: dict[str, Any], station_context: dict[str, Any] | None) -> dict[str, Any]:
        if station_context is None:
            return {"reject": False, "score_boost": 0.0}

        station_a_position = station_context.get("station_a_position", {})
        station_b_position = station_context.get("station_b_position", {})
        station_span_meters = float(station_context.get("station_span_meters") or 0.0)
        coordinates = osm_feature.get("geometry", {}).get("coordinates") or [None, None]
        if coordinates[0] is None or coordinates[1] is None:
            return {"reject": False, "score_boost": 0.0}

        projection = project_point_onto_station_line(
            station_a_position.get("PositionLon"),
            station_a_position.get("PositionLat"),
            station_b_position.get("PositionLon"),
            station_b_position.get("PositionLat"),
            coordinates[0],
            coordinates[1],
        )
        offset_meters = float(projection["offset_meters"])
        if offset_meters > max(station_span_meters * OSM_STATION_CORRIDOR_MAX_OFFSET_MULTIPLIER, OSM_STATION_CORRIDOR_MAX_OFFSET_METERS):
            return {"reject": True, "score_boost": 0.0, "offset_meters": offset_meters}
        if offset_meters <= 300.0:
            score_boost = 32.0
        elif offset_meters <= 750.0:
            score_boost = 24.0
        elif offset_meters <= 1_500.0:
            score_boost = 16.0
        elif offset_meters <= 3_000.0:
            score_boost = 8.0
        else:
            score_boost = 0.0
        return {"reject": False, "score_boost": score_boost, "offset_meters": offset_meters}

    def _matched_geometry_is_plausible(self, crossing: CrossingRecord, *, station_context: dict[str, Any] | None) -> bool:
        if crossing.geometry is None:
            return False
        assessment = self._corridor_match_assessment(
            {
                "geometry": {
                    "coordinates": [crossing.geometry.lon, crossing.geometry.lat],
                }
            },
            station_context,
        )
        return not assessment.get("reject", False)

    def _prefer_plausible_local_osm_candidate(
        self,
        official: CrossingRecord,
        matched_feature: dict[str, Any] | None,
        matched_score: float,
        matched_method: str | None,
        osm_features: list[dict[str, Any]],
        *,
        station_context: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, float, str | None]:
        if (
            matched_feature is None
            or station_context is None
            or self.station_graph_service is None
            or self.station_graph_service.rail_path_service is None
        ):
            return (matched_feature, matched_score, matched_method)

        current_path_assessment = self._evaluate_osm_path_candidate(matched_feature, station_context=station_context)
        if current_path_assessment is not None and current_path_assessment["plausible"]:
            return (matched_feature, matched_score, matched_method)

        current_coordinates = matched_feature.get("geometry", {}).get("coordinates") or [None, None]
        if current_coordinates[0] is None or current_coordinates[1] is None:
            return (matched_feature, matched_score, matched_method)

        plausible_candidates: list[tuple[float, float, float, dict[str, Any], str | None]] = []
        for feature in osm_features:
            if feature is matched_feature:
                continue

            candidate_coordinates = feature.get("geometry", {}).get("coordinates") or [None, None]
            if candidate_coordinates[0] is None or candidate_coordinates[1] is None:
                continue

            local_distance_meters = haversine_meters(
                float(current_coordinates[1]),
                float(current_coordinates[0]),
                float(candidate_coordinates[1]),
                float(candidate_coordinates[0]),
            )
            if local_distance_meters > OSM_LOCAL_SIBLING_RADIUS_METERS:
                continue

            candidate_score, candidate_method = self._score_match(official, feature, station_context=station_context)
            if candidate_score < matched_score:
                continue

            candidate_path_assessment = self._evaluate_osm_path_candidate(feature, station_context=station_context)
            if candidate_path_assessment is None or not candidate_path_assessment["plausible"]:
                continue

            plausible_candidates.append(
                (
                    candidate_score,
                    float(candidate_path_assessment["total_distance_meters"]),
                    local_distance_meters,
                    feature,
                    candidate_method,
                )
            )

        if not plausible_candidates:
            return (matched_feature, matched_score, matched_method)

        plausible_candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        best_score, _, _, best_feature, best_method = plausible_candidates[0]
        return (best_feature, best_score, best_method)

    def _evaluate_osm_path_candidate(
        self,
        osm_feature: dict[str, Any],
        *,
        station_context: dict[str, Any] | None,
    ) -> dict[str, float | bool] | None:
        if (
            station_context is None
            or self.station_graph_service is None
            or self.station_graph_service.rail_path_service is None
        ):
            return None

        station_a_position = station_context.get("station_a_position", {})
        station_b_position = station_context.get("station_b_position", {})
        station_a_lon = station_a_position.get("PositionLon")
        station_a_lat = station_a_position.get("PositionLat")
        station_b_lon = station_b_position.get("PositionLon")
        station_b_lat = station_b_position.get("PositionLat")
        coordinates = osm_feature.get("geometry", {}).get("coordinates") or [None, None]
        if (
            station_a_lon is None
            or station_a_lat is None
            or station_b_lon is None
            or station_b_lat is None
            or coordinates[0] is None
            or coordinates[1] is None
        ):
            return None

        point = GeoPoint(lat=float(coordinates[1]), lon=float(coordinates[0]))
        path_result = self.station_graph_service.rail_path_service.compute_segment_ratio(
            station_a_position=station_a_position,
            station_b_position=station_b_position,
            crossing_point=point,
            crossing_way_ids=osm_feature.get("properties", {}).get("rail_way_ids") or None,
        )
        if path_result is None:
            return None

        geometry_ratio = point_ratio_between_stations(
            float(station_a_lon),
            float(station_a_lat),
            float(station_b_lon),
            float(station_b_lat),
            point.lon,
            point.lat,
        )
        total_distance_meters = path_result.distance_from_station_a_meters + path_result.distance_to_station_b_meters
        station_span_meters = float(station_context.get("station_span_meters") or 0.0)
        if station_span_meters <= 0.0:
            station_span_meters = haversine_meters(
                float(station_a_lat),
                float(station_a_lon),
                float(station_b_lat),
                float(station_b_lon),
            )
        distance_multiple = total_distance_meters / station_span_meters if station_span_meters > 0 else None
        ratio_delta_from_projection = abs(path_result.ratio - geometry_ratio)

        plausible = True
        if (
            distance_multiple is not None
            and total_distance_meters > max(station_span_meters * OSM_PATH_MAX_DISTANCE_MULTIPLIER, OSM_PATH_MAX_DISTANCE_METERS)
        ):
            plausible = False
        elif (
            distance_multiple is not None
            and ratio_delta_from_projection >= OSM_PATH_GEOMETRY_DELTA_THRESHOLD
            and total_distance_meters
            > max(station_span_meters * OSM_PATH_GEOMETRY_DISTANCE_MULTIPLIER, OSM_PATH_GEOMETRY_MIN_DISTANCE_METERS)
        ):
            plausible = False

        return {
            "plausible": plausible,
            "ratio": path_result.ratio,
            "total_distance_meters": total_distance_meters,
        }

    def _clear_osm_match(self, crossing: CrossingRecord) -> None:
        crossing.geometry = None
        crossing.matched_osm_id = None
        crossing.match_score = 0.0
        crossing.match_method = f"{crossing.match_method}_rejected_by_station_corridor" if crossing.match_method else "rejected_by_station_corridor"
        crossing.geolocation_confidence = "low"
        crossing.manual_mapping_applied = False
        crossing.osm_road_names = []
        crossing.osm_rail_names = []
        crossing.osm_rail_way_ids = []
        crossing.osm_tags = {}

    def _find_osm_feature_by_id(self, osm_features: list[dict[str, Any]], osm_id: int | str | None) -> dict[str, Any] | None:
        if osm_id is None:
            return None
        for feature in osm_features:
            if feature.get("properties", {}).get("osm_id") == osm_id:
                return feature
        return None

    def _load_manual_mapping_lookup(self) -> dict[str, dict[str, Any]]:
        if not self.settings.manual_mappings_json_path.exists():
            return {}

        payload = json.loads(self.settings.manual_mappings_json_path.read_text(encoding="utf-8"))
        mappings = payload.get("mappings", [])
        lookup: dict[str, dict[str, Any]] = {}
        for item in mappings:
            crossing_id = item.get("crossing_id")
            osm_id = item.get("osm_id")
            if crossing_id and (osm_id is not None or self._manual_geometry_from_mapping(item) is not None):
                lookup[str(crossing_id)] = item
        return lookup

    def _manual_geometry_from_mapping(self, mapping: dict[str, Any] | None) -> GeoPoint | None:
        if mapping is None:
            return None

        geometry = mapping.get("geometry")
        if isinstance(geometry, dict):
            lat = geometry.get("lat")
            lon = geometry.get("lon")
            if lat is not None and lon is not None:
                return GeoPoint(lat=float(lat), lon=float(lon))
            coordinates = geometry.get("coordinates")
            if isinstance(coordinates, list) and len(coordinates) >= 2:
                lon = coordinates[0]
                lat = coordinates[1]
                if lat is not None and lon is not None:
                    return GeoPoint(lat=float(lat), lon=float(lon))

        coordinates = mapping.get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            lon = coordinates[0]
            lat = coordinates[1]
            if lat is not None and lon is not None:
                return GeoPoint(lat=float(lat), lon=float(lon))

        lat = mapping.get("lat")
        lon = mapping.get("lon")
        if lat is not None and lon is not None:
            return GeoPoint(lat=float(lat), lon=float(lon))

        return None

    def _match_official_to_osm(
        self,
        official: CrossingRecord,
        osm_features: list[dict[str, Any]],
        *,
        station_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, float, str | None, ConfidenceLevel]:
        best_feature: dict[str, Any] | None = None
        best_score = 0.0
        best_method: str | None = None
        second_best = 0.0

        for feature in osm_features:
            score, method = self._score_match(official, feature, station_context=station_context)
            if score > best_score:
                second_best = best_score
                best_feature = feature
                best_score = score
                best_method = method
            elif score > second_best:
                second_best = score

        gap = best_score - second_best
        if best_feature is None or best_score < 45:
            return (None, 0.0, None, "low")
        if best_score >= 80 and gap >= 15:
            return (best_feature, best_score, best_method, "high")
        return (best_feature, best_score, best_method, "medium")

    def _score_match(
        self,
        official: CrossingRecord,
        osm_feature: dict[str, Any],
        *,
        station_context: dict[str, Any] | None = None,
    ) -> tuple[float, str | None]:
        properties = osm_feature.get("properties", {})
        official_name = official.normalized_name
        if not official_name:
            return (0.0, None)

        corridor_assessment = self._corridor_match_assessment(osm_feature, station_context)
        if corridor_assessment.get("reject"):
            return (0.0, None)

        official_line = normalize_text(official.line)
        rail_names = properties.get("rail_names", [])
        line_matches = bool(official_line) and any(
            official_line in normalize_text(value) or normalize_text(value) in official_line
            for value in rail_names
            if value
        )

        candidates = [
            (properties.get("normalized_name") or "", "node_name"),
            *[(normalize_text(value), "road_name") for value in properties.get("road_names", [])],
            *[(normalize_text(value), "rail_name") for value in properties.get("rail_names", [])],
        ]

        best_score = 0.0
        best_method: str | None = None
        for candidate_value, method in candidates:
            if not candidate_value:
                continue
            if candidate_value == official_name:
                score = 95.0 if method == "node_name" else 88.0
            elif official_name in candidate_value or candidate_value in official_name:
                score = 72.0 if method == "road_name" else 60.0
            else:
                continue

            if method in {"node_name", "road_name"} and rail_names and not line_matches:
                continue

            if official.km_value_meters and properties.get("railway_position_meters"):
                if abs(official.km_value_meters - properties["railway_position_meters"]) <= 500:
                    score += 8.0

            if line_matches:
                score += 5.0

            score += float(corridor_assessment.get("score_boost", 0.0))

            if score > best_score:
                best_score = score
                best_method = method

        return (best_score, best_method)
