from __future__ import annotations

import asyncio
import json
import os
import time

from backend.app.config import Settings
from backend.app.models.crossing import CrossingRecord
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.manual_mapping import ManualOsmMappingService


def test_manual_mapping_override_applies_geometry(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.manual_mappings_json_path = tmp_path / "manual_osm_mappings.json"
    settings.manual_mappings_json_path.write_text(
        json.dumps(
            {
                "metadata": {"updated_at": "2026-05-20T00:00:00+00:00", "count": 1},
                "mappings": [
                    {
                        "crossing_id": "sample-crossing",
                        "osm_id": 123,
                        "note": "manual",
                        "updated_at": "2026-05-20T00:00:00+00:00",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    catalog = CrossingCatalogService(None, None, settings)  # type: ignore[arg-type]
    official_record = CrossingRecord(
        crossing_id="sample-crossing",
        name="樣本平交道",
        normalized_name="樣本平交道",
        line="宜蘭線",
        km_marker="K001+000",
        km_prefix="",
        km_value_meters=1000,
        road_type="村里",
        station_pair_text="甲站-乙站",
        station_a_name="甲站",
        station_b_name="乙站",
        county="測試縣",
        source_page=1,
        source_row_index=1,
    )
    osm_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "osm-node-123",
                "geometry": {"type": "Point", "coordinates": [121.5, 25.0]},
                "properties": {
                    "osm_id": 123,
                    "name": "未命名",
                    "road_names": ["測試路"],
                    "rail_names": ["宜蘭線"],
                    "tags": {"railway": "level_crossing"},
                },
            }
        ],
    }

    curated = catalog._build_curated_geojson([official_record], osm_geojson)

    assert curated["metadata"]["mapped_count"] == 1
    feature = curated["features"][0]
    assert feature["geometry"]["coordinates"] == [121.5, 25.0]
    assert feature["properties"]["matched_osm_id"] == 123
    assert feature["properties"]["match_method"] == "manual_override"
    assert feature["properties"]["geolocation_confidence"] == "high"
    assert feature["properties"]["manual_mapping_applied"] is True


class _StubCatalog:
    async def load(self) -> dict:
        return {"type": "FeatureCollection", "features": []}


class _StubOsmEnricher:
    async def build_geojson(self, *, force_refresh: bool = False) -> dict:
        return {"type": "FeatureCollection", "features": []}


class _StubStationGraph:
    async def enrich_crossing_properties(self, properties: dict) -> dict:
        enriched = dict(properties)
        enriched["station_a_id"] = "1000"
        enriched["station_a_position"] = {"PositionLat": 23.8295, "PositionLon": 120.6408}
        enriched["station_b_id"] = "1001"
        enriched["station_b_position"] = {"PositionLat": 23.8552, "PositionLon": 120.7421}
        return enriched


class _FailingStationGraph:
    async def enrich_crossing_properties(self, properties: dict) -> dict:
        raise RuntimeError("TDX unavailable")


class _StubScraper:
    def __init__(self, records: list[CrossingRecord]) -> None:
        self.records = records

    async def scrape_all(self, *, force_refresh: bool = False) -> list[CrossingRecord]:
        return self.records


class _StubGeojsonEnricher:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def build_geojson(self, *, force_refresh: bool = False) -> dict:
        return self.payload


def test_manual_review_entries_include_station_positions(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.unmatched_analysis_json_path = tmp_path / "unmatched_crossings_analysis.json"
    settings.manual_mappings_json_path = tmp_path / "manual_osm_mappings.json"
    settings.unmatched_analysis_json_path.write_text(
        json.dumps(
            {
                "metadata": {"unmatched_count": 1},
                "summary": {},
                "entries": [
                    {
                        "crossing_id": "sample-review",
                        "name": "樣本平交道",
                        "line": "集集線",
                        "km_marker": "K014+651",
                        "km_value_meters": 14651,
                        "station_pair_text": "濁水-龍泉",
                        "station_a_name": "濁水",
                        "station_b_name": "龍泉",
                        "county": "南投縣",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service = ManualOsmMappingService(_StubCatalog(), _StubOsmEnricher(), settings, _StubStationGraph())
    payload = asyncio.run(service.list_review_entries(include_resolved=True))

    entry = payload["entries"][0]
    assert entry["station_a_id"] == "1000"
    assert entry["station_a_position"] == {"PositionLat": 23.8295, "PositionLon": 120.6408}
    assert entry["station_b_id"] == "1001"
    assert entry["station_b_position"] == {"PositionLat": 23.8552, "PositionLon": 120.7421}


def test_manual_review_entries_fallback_when_station_lookup_fails(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.unmatched_analysis_json_path = tmp_path / "unmatched_crossings_analysis.json"
    settings.manual_mappings_json_path = tmp_path / "manual_osm_mappings.json"
    settings.unmatched_analysis_json_path.write_text(
        json.dumps(
            {
                "metadata": {"unmatched_count": 1},
                "summary": {},
                "entries": [
                    {
                        "crossing_id": "sample-review",
                        "name": "樣本平交道",
                        "line": "集集線",
                        "km_marker": "K014+651",
                        "km_value_meters": 14651,
                        "station_pair_text": "濁水-龍泉",
                        "station_a_name": "濁水",
                        "station_b_name": "龍泉",
                        "county": "南投縣",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    service = ManualOsmMappingService(_StubCatalog(), _StubOsmEnricher(), settings, _FailingStationGraph())
    payload = asyncio.run(service.list_review_entries(include_resolved=True))

    entry = payload["entries"][0]
    assert entry["station_a_name"] == "濁水"
    assert "station_a_position" not in entry
    assert "station_b_position" not in entry


def test_catalog_load_refreshes_when_manual_mapping_file_is_newer(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.curated_crossings_geojson_path = tmp_path / "crossings_curated.geojson"
    settings.full_crossings_geojson_path = tmp_path / "crossings_full.geojson"
    settings.curated_tainan_crossings_geojson_path = tmp_path / "crossings_curated_tainan.geojson"
    settings.official_tainan_crossings_json_path = tmp_path / "crossings_official_tainan.json"
    settings.manual_mappings_json_path = tmp_path / "manual_osm_mappings.json"
    settings.official_crossings_json_path = tmp_path / "crossings_official.json"
    settings.osm_geojson_path = tmp_path / "osm_crossings.geojson"

    settings.curated_crossings_geojson_path.write_text(
        json.dumps({"type": "FeatureCollection", "metadata": {"mapped_count": 0}, "features": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    settings.manual_mappings_json_path.write_text(
        json.dumps(
            {
                "metadata": {"updated_at": "2026-05-20T09:05:00+00:00", "count": 1},
                "mappings": [
                    {
                        "crossing_id": "sample-crossing",
                        "osm_id": 123,
                        "note": None,
                        "updated_at": "2026-05-20T09:05:00+00:00",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    now = time.time()
    os.utime(settings.curated_crossings_geojson_path, (now - 10, now - 10))
    os.utime(settings.manual_mappings_json_path, (now, now))

    official_record = CrossingRecord(
        crossing_id="sample-crossing",
        name="樣本平交道",
        normalized_name="樣本平交道",
        line="宜蘭線",
        km_marker="K001+000",
        km_prefix="",
        km_value_meters=1000,
        road_type="村里",
        station_pair_text="甲站-乙站",
        station_a_name="甲站",
        station_b_name="乙站",
        county="測試縣",
        source_page=1,
        source_row_index=1,
    )
    osm_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "osm-node-123",
                "geometry": {"type": "Point", "coordinates": [121.5, 25.0]},
                "properties": {
                    "osm_id": 123,
                    "name": "未命名",
                    "road_names": ["測試路"],
                    "rail_names": ["宜蘭線"],
                    "tags": {"railway": "level_crossing"},
                },
            }
        ],
    }

    catalog = CrossingCatalogService(_StubScraper([official_record]), _StubGeojsonEnricher(osm_geojson), settings)
    curated = asyncio.run(catalog.load())

    assert curated["metadata"]["mapped_count"] == 1
    feature = curated["features"][0]
    assert feature["properties"]["matched_osm_id"] == 123
    assert feature["properties"]["match_method"] == "manual_override"
    assert feature["properties"]["manual_mapping_applied"] is True
    assert settings.full_crossings_geojson_path.exists()
    assert settings.curated_tainan_crossings_geojson_path.exists()
    assert settings.official_tainan_crossings_json_path.exists()


def test_active_dataset_excludes_crossings_without_geometry() -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    catalog = CrossingCatalogService(None, None, settings)  # type: ignore[arg-type]

    full_dataset = {
        "type": "FeatureCollection",
        "metadata": {"mapped_count": 1},
        "features": [
            {
                "type": "Feature",
                "id": "mapped",
                "geometry": {"type": "Point", "coordinates": [121.5, 25.0]},
                "properties": {"crossing_id": "mapped", "county": "臺南市"},
            },
            {
                "type": "Feature",
                "id": "unmapped",
                "geometry": None,
                "properties": {"crossing_id": "unmapped", "county": "臺南市"},
            },
        ],
    }

    active_dataset = catalog._build_active_geojson(full_dataset)
    tainan_dataset = catalog._build_geojson_county_subset(active_dataset, county="臺南市")

    assert len(active_dataset["features"]) == 1
    assert active_dataset["metadata"]["excluded_feature_count"] == 1
    assert active_dataset["features"][0]["properties"]["crossing_id"] == "mapped"
    assert len(tainan_dataset["features"]) == 1