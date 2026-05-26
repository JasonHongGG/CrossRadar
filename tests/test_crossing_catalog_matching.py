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


def test_station_corridor_rejects_far_exact_name_match() -> None:
    catalog = CrossingCatalogService(None, None)  # type: ignore[arg-type]
    official = CrossingRecord(
        crossing_id="zhongshan",
        name="中山路",
        normalized_name="中山路",
        line="宜蘭線",
        km_marker="K080+438",
        km_prefix="",
        km_value_meters=80438,
        road_type="鎮道",
        station_pair_text="羅東-冬山",
        station_a_name="羅東",
        station_b_name="冬山",
        county="宜蘭縣",
        source_page=1,
        source_row_index=1,
    )
    station_context = {
        "station_a_position": {"PositionLon": 121.7665, "PositionLat": 24.67795},
        "station_b_position": {"PositionLon": 121.79205, "PositionLat": 24.63665},
        "station_span_meters": 4949.1,
    }
    osm_feature = {
        "geometry": {"coordinates": [120.5928607, 22.3715402]},
        "properties": {
            "normalized_name": "中山路",
            "road_names": ["中山路二段", "中山路"],
            "rail_names": [],
            "railway_position_meters": None,
        },
    }

    score, method = catalog._score_match(official, osm_feature, station_context=station_context)

    assert score == 0.0
    assert method is None


def test_station_corridor_prefers_local_candidate_over_far_exact_name() -> None:
    catalog = CrossingCatalogService(None, None)  # type: ignore[arg-type]
    official = CrossingRecord(
        crossing_id="zhongshan",
        name="中山路",
        normalized_name="中山路",
        line="宜蘭線",
        km_marker="K080+438",
        km_prefix="",
        km_value_meters=80438,
        road_type="鎮道",
        station_pair_text="羅東-冬山",
        station_a_name="羅東",
        station_b_name="冬山",
        county="宜蘭縣",
        source_page=1,
        source_row_index=1,
    )
    station_context = {
        "station_a_position": {"PositionLon": 121.7665, "PositionLat": 24.67795},
        "station_b_position": {"PositionLon": 121.79205, "PositionLat": 24.63665},
        "station_span_meters": 4949.1,
    }
    local_feature = {
        "geometry": {"coordinates": [121.7744407, 24.6750453]},
        "properties": {
            "osm_id": 649286632,
            "normalized_name": "中山路平交道",
            "road_names": ["中山路二段", "7丙"],
            "rail_names": ["宜蘭線", "台鐵東部幹線"],
            "railway_position_meters": None,
        },
    }
    far_feature = {
        "geometry": {"coordinates": [120.5928607, 22.3715402]},
        "properties": {
            "osm_id": 1175229936,
            "normalized_name": "中山路",
            "road_names": ["中山路二段", "中山路"],
            "rail_names": [],
            "railway_position_meters": None,
        },
    }

    matched_feature, score, method, confidence = catalog._match_official_to_osm(
        official,
        [far_feature, local_feature],
        station_context=station_context,
    )

    assert matched_feature == local_feature
    assert method in {"node_name", "road_name"}
    assert confidence in {"high", "medium"}
    assert score > 80.0