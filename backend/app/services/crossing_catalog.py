from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.models.crossing import ConfidenceLevel, CrossingRecord, GeoPoint
from backend.app.services.crossing_scraper import TraOfficialCrossingScraper
from backend.app.services.osm_enricher import OsmEnricher
from backend.app.services.route_reference import RouteReferenceService
from backend.app.utils import normalize_text


class CrossingCatalogService:
    def __init__(
        self,
        scraper: TraOfficialCrossingScraper,
        osm_enricher: OsmEnricher,
        settings: Settings | None = None,
        route_reference_service: RouteReferenceService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.scraper = scraper
        self.osm_enricher = osm_enricher
        self.route_reference_service = route_reference_service or RouteReferenceService(self.settings)

    async def refresh(self, *, force_refresh: bool = False) -> dict[str, Any]:
        official_records = await self.scraper.scrape_all(force_refresh=force_refresh)
        osm_geojson = await self.osm_enricher.build_geojson(force_refresh=force_refresh)
        full_dataset = self._build_curated_geojson(official_records, osm_geojson)
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

    def _build_curated_geojson(self, official_records: list[CrossingRecord], osm_geojson: dict[str, Any]) -> dict[str, Any]:
        osm_features = osm_geojson.get("features", [])
        manual_mapping_lookup = self._load_manual_mapping_lookup()
        route_reference_metadata = self.route_reference_service.metadata()
        features: list[dict[str, Any]] = []
        mapped_count = 0
        authoritative_pair_count = 0

        for official in official_records:
            updated = self.route_reference_service.apply(official.model_copy(deep=True))
            if updated.authoritative_reference_applied:
                authoritative_pair_count += 1

            manual_mapping = manual_mapping_lookup.get(official.crossing_id)
            if manual_mapping is not None:
                matched_feature = self._find_osm_feature_by_id(osm_features, manual_mapping.get("osm_id"))
                if matched_feature is not None:
                    score = 100.0
                    match_method = "manual_override"
                    confidence = "high"
                else:
                    matched_feature, score, match_method, confidence = self._match_official_to_osm(official, osm_features)
            else:
                matched_feature, score, match_method, confidence = self._match_official_to_osm(official, osm_features)

            updated.match_score = score
            updated.match_method = match_method
            updated.geolocation_confidence = confidence
            updated.manual_mapping_applied = matched_feature is not None and manual_mapping is not None

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
                    mapped_count += 1

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
            if crossing_id and osm_id is not None:
                lookup[str(crossing_id)] = item
        return lookup

    def _match_official_to_osm(
        self,
        official: CrossingRecord,
        osm_features: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, float, str | None, ConfidenceLevel]:
        best_feature: dict[str, Any] | None = None
        best_score = 0.0
        best_method: str | None = None
        second_best = 0.0

        for feature in osm_features:
            score, method = self._score_match(official, feature)
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

    def _score_match(self, official: CrossingRecord, osm_feature: dict[str, Any]) -> tuple[float, str | None]:
        properties = osm_feature.get("properties", {})
        official_name = official.normalized_name
        if not official_name:
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

            if score > best_score:
                best_score = score
                best_method = method

        return (best_score, best_method)
