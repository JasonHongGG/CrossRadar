from __future__ import annotations

import json
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.models.crossing import ConfidenceLevel, CrossingRecord, GeoPoint
from backend.app.services.crossing_scraper import TraOfficialCrossingScraper
from backend.app.services.osm_enricher import OsmEnricher
from backend.app.utils import normalize_text


class CrossingCatalogService:
    def __init__(
        self,
        scraper: TraOfficialCrossingScraper,
        osm_enricher: OsmEnricher,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.scraper = scraper
        self.osm_enricher = osm_enricher

    async def refresh(self, *, force_refresh: bool = False) -> dict[str, Any]:
        official_records = await self.scraper.scrape_all(force_refresh=force_refresh)
        osm_geojson = await self.osm_enricher.build_geojson(force_refresh=force_refresh)
        curated = self._build_curated_geojson(official_records, osm_geojson)
        self.settings.curated_crossings_geojson_path.write_text(
            json.dumps(curated, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return curated

    async def load(self) -> dict[str, Any]:
        if not self.settings.curated_crossings_geojson_path.exists():
            return await self.refresh(force_refresh=False)
        return json.loads(self.settings.curated_crossings_geojson_path.read_text(encoding="utf-8"))

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

    def _build_curated_geojson(self, official_records: list[CrossingRecord], osm_geojson: dict[str, Any]) -> dict[str, Any]:
        osm_features = osm_geojson.get("features", [])
        features: list[dict[str, Any]] = []
        mapped_count = 0

        for official in official_records:
            matched_feature, score, match_method, confidence = self._match_official_to_osm(official, osm_features)
            updated = official.model_copy(deep=True)
            updated.match_score = score
            updated.match_method = match_method
            updated.geolocation_confidence = confidence

            if matched_feature is not None and confidence in ("high", "medium"):
                properties = matched_feature.get("properties", {})
                geometry = matched_feature.get("geometry", {})
                coordinates = geometry.get("coordinates") or [None, None]
                if coordinates[0] is not None and coordinates[1] is not None:
                    updated.geometry = GeoPoint(lat=coordinates[1], lon=coordinates[0])
                    updated.matched_osm_id = properties.get("osm_id")
                    updated.osm_road_names = properties.get("road_names", [])
                    updated.osm_rail_names = properties.get("rail_names", [])
                    updated.osm_tags = properties.get("tags", {})
                    mapped_count += 1

            features.append(updated.to_feature())

        return {
            "type": "FeatureCollection",
            "metadata": {
                "source": "official+osm",
                "official_count": len(official_records),
                "mapped_count": mapped_count,
                "osm_feature_count": len(osm_features),
                "osm_raw_path": str(self.settings.osm_raw_json_path),
            },
            "features": features,
        }

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

            if official.km_value_meters and properties.get("railway_position_meters"):
                if abs(official.km_value_meters - properties["railway_position_meters"]) <= 500:
                    score += 8.0

            if normalize_text(official.line) and any(
                normalize_text(official.line) in normalize_text(value) for value in properties.get("rail_names", [])
            ):
                score += 5.0

            if score > best_score:
                best_score = score
                best_method = method

        return (best_score, best_method)
