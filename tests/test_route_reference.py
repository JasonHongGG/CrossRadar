from __future__ import annotations

import json

from backend.app.config import Settings
from backend.app.models.crossing import CrossingRecord
from backend.app.services.crossing_catalog import CrossingCatalogService


def _build_settings(tmp_path) -> Settings:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.route_reference_json_path = tmp_path / "tainan_route_reference.json"
    settings.manual_mappings_json_path = tmp_path / "manual_osm_mappings.json"
    settings.manual_mappings_json_path.write_text(
        json.dumps({"metadata": {"count": 0}, "mappings": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return settings


def test_catalog_applies_tainan_pair_override_by_range(tmp_path) -> None:
    settings = _build_settings(tmp_path)
    settings.route_reference_json_path.write_text(
        json.dumps(
            {
                "metadata": {"scope": "test"},
                "rules": [
                    {
                        "id": "urban-range",
                        "match": {
                            "county": "臺南市",
                            "line": "縱貫線",
                            "km_range": {"gte": 355300, "lt": 357800},
                        },
                        "override": {
                            "station_pair_text": "大橋-臺南",
                            "station_a_name": "大橋",
                            "station_b_name": "臺南",
                            "station_a_route_km_meters": 355300,
                            "station_b_route_km_meters": 357800,
                            "station_route_reference_note": "official anchor",
                        },
                        "pair_source": "authoritative_reference",
                        "reference_note": "range override",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    record = CrossingRecord(
        crossing_id="sample-urban",
        name="東豐路",
        normalized_name="東豐路",
        line="縱貫線",
        km_marker="K357+184",
        km_prefix="",
        km_value_meters=357184,
        road_type="市道",
        query_station_pair_text="永康-台南",
        query_station_a_name="永康",
        query_station_b_name="台南",
        station_pair_text="永康-台南",
        station_a_name="永康",
        station_b_name="台南",
        county="臺南市",
        source_page=1,
        source_row_index=1,
    )

    catalog = CrossingCatalogService(None, None, settings)  # type: ignore[arg-type]
    curated = catalog._build_curated_geojson([record], {"type": "FeatureCollection", "features": []})

    feature = curated["features"][0]
    properties = feature["properties"]
    assert properties["query_station_pair_text"] == "永康-台南"
    assert properties["station_pair_text"] == "大橋-臺南"
    assert properties["station_a_name"] == "大橋"
    assert properties["station_b_name"] == "臺南"
    assert properties["station_pair_source"] == "authoritative_reference"
    assert properties["authoritative_reference_applied"] is True
    assert properties["station_a_route_km_meters"] == 355300
    assert properties["station_b_route_km_meters"] == 357800
    assert curated["metadata"]["authoritative_pair_count"] == 1


def test_catalog_applies_explicit_fourwei_override(tmp_path) -> None:
    settings = _build_settings(tmp_path)
    settings.route_reference_json_path.write_text(
        json.dumps(
            {
                "metadata": {"scope": "test"},
                "rules": [
                    {
                        "id": "fourwei",
                        "match": {
                            "county": "臺南市",
                            "line": "縱貫線",
                            "name": "四維路",
                            "km_value_meters": 351802,
                        },
                        "override": {
                            "station_pair_text": "永康-大橋",
                            "station_a_name": "永康",
                            "station_b_name": "大橋",
                        },
                        "pair_source": "authoritative_reference",
                        "reference_note": "incident override",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    record = CrossingRecord(
        crossing_id="fourwei",
        name="四維路",
        normalized_name="四維路",
        line="縱貫線",
        km_marker="K351+802",
        km_prefix="",
        km_value_meters=351802,
        road_type="市道",
        query_station_pair_text="永康-台南",
        query_station_a_name="永康",
        query_station_b_name="台南",
        station_pair_text="永康-台南",
        station_a_name="永康",
        station_b_name="台南",
        county="臺南市",
        source_page=1,
        source_row_index=1,
    )

    catalog = CrossingCatalogService(None, None, settings)  # type: ignore[arg-type]
    curated = catalog._build_curated_geojson([record], {"type": "FeatureCollection", "features": []})

    properties = curated["features"][0]["properties"]
    assert properties["station_pair_text"] == "永康-大橋"
    assert properties["station_a_name"] == "永康"
    assert properties["station_b_name"] == "大橋"
    assert properties["station_pair_reference_id"] == "fourwei"


def test_catalog_applies_explicit_crossing_override_by_id(tmp_path) -> None:
    settings = _build_settings(tmp_path)
    settings.route_reference_json_path.write_text(
        json.dumps(
            {
                "metadata": {"scope": "test"},
                "rules": [
                    {
                        "id": "bade-override",
                        "match": {
                            "crossing_id": "八德街-中興一號特種支線-k001705",
                        },
                        "override": {
                            "station_pair_text": "鶯歌-鳳鳴火車站",
                            "station_a_name": "鶯歌",
                            "station_b_name": "鳳鳴火車站",
                        },
                        "pair_source": "explicit_crossing_override",
                        "reference_note": "user override",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    record = CrossingRecord(
        crossing_id="八德街-中興一號特種支線-k001705",
        name="八德街",
        normalized_name="八德街",
        line="中興一號特種支線",
        km_marker="K001+705",
        km_prefix="",
        km_value_meters=1705,
        road_type="市道",
        query_station_pair_text="鶯歌-基地",
        query_station_a_name="鶯歌",
        query_station_b_name="基地",
        station_pair_text="鶯歌-基地",
        station_a_name="鶯歌",
        station_b_name="基地",
        county="新北市",
        source_page=1,
        source_row_index=1,
    )

    catalog = CrossingCatalogService(None, None, settings)  # type: ignore[arg-type]
    curated = catalog._build_curated_geojson([record], {"type": "FeatureCollection", "features": []})

    properties = curated["features"][0]["properties"]
    assert properties["query_station_b_name"] == "基地"
    assert properties["station_pair_text"] == "鶯歌-鳳鳴火車站"
    assert properties["station_b_name"] == "鳳鳴火車站"
    assert properties["station_pair_source"] == "explicit_crossing_override"
    assert properties["station_pair_reference_id"] == "bade-override"