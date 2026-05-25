from __future__ import annotations

from backend.app.models.crossing import CrossingRecord
from backend.app.services.crossing_catalog import CrossingCatalogService


def _build_official_record() -> CrossingRecord:
    return CrossingRecord(
        crossing_id="datong",
        name="大同路141巷",
        normalized_name="大同路141巷",
        line="縱貫線",
        km_marker="K359+197",
        km_prefix="",
        km_value_meters=359197,
        road_type="巷道",
        station_pair_text="台南-保安",
        station_a_name="台南",
        station_b_name="保安",
        county="臺南市",
        source_page=1,
        source_row_index=1,
    )


def test_road_name_match_is_rejected_when_rail_line_conflicts() -> None:
    catalog = CrossingCatalogService(None, None)  # type: ignore[arg-type]
    official = _build_official_record()
    osm_feature = {
        "properties": {
            "normalized_name": "",
            "road_names": ["大同路141巷"],
            "rail_names": ["高雄環狀輕軌"],
            "railway_position_meters": None,
        }
    }

    score, method = catalog._score_match(official, osm_feature)

    assert score == 0.0
    assert method is None


def test_exact_name_match_is_rejected_when_rail_line_conflicts() -> None:
    catalog = CrossingCatalogService(None, None)  # type: ignore[arg-type]
    official = _build_official_record()
    osm_feature = {
        "properties": {
            "normalized_name": "大同路141巷",
            "road_names": [],
            "rail_names": ["內灣線"],
            "railway_position_meters": None,
        }
    }

    score, method = catalog._score_match(official, osm_feature)

    assert score == 0.0
    assert method is None


def test_road_name_match_can_still_score_when_rail_line_agrees() -> None:
    catalog = CrossingCatalogService(None, None)  # type: ignore[arg-type]
    official = _build_official_record()
    osm_feature = {
        "properties": {
            "normalized_name": "",
            "road_names": ["大同路141巷"],
            "rail_names": ["縱貫線"],
            "railway_position_meters": None,
        }
    }

    score, method = catalog._score_match(official, osm_feature)

    assert method == "road_name"
    assert score > 72.0