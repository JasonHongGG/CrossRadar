from __future__ import annotations

import json

from backend.app.config import Settings
from backend.app.models.crossing import CrossingRecord
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.rail_path import RailPathRatio


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


class _StubRailPathService:
    def compute_segment_ratio(self, *, crossing_way_ids=None, **kwargs):  # type: ignore[no-untyped-def]
        way_id = (crossing_way_ids or [None])[0]
        if way_id == 321033991:
            return RailPathRatio(
                ratio=0.8732816679172966,
                distance_from_station_a_meters=20143.0,
                distance_to_station_b_meters=2929.061887899083,
                crossing_snap_distance_meters=0.0,
                station_a_snap_distance_meters=18.0,
                station_b_snap_distance_meters=8.9,
            )
        if way_id == 321033995:
            return RailPathRatio(
                ratio=0.5161377079771224,
                distance_from_station_a_meters=3118.0,
                distance_to_station_b_meters=2923.4105030465425,
                crossing_snap_distance_meters=0.0,
                station_a_snap_distance_meters=18.0,
                station_b_snap_distance_meters=8.9,
            )
        return None


class _StubStationGraphService:
    def __init__(self) -> None:
        self.rail_path_service = _StubRailPathService()


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


def test_parallel_track_tie_break_prefers_plausible_sibling_node(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.manual_mappings_json_path = tmp_path / "manual_osm_mappings.json"
    settings.manual_mappings_json_path.write_text(
        json.dumps(
            {
                "metadata": {"updated_at": "2026-05-27T00:00:00+00:00", "count": 0},
                "mappings": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    catalog = CrossingCatalogService(
        None,
        None,
        settings,
        station_graph_service=_StubStationGraphService(),  # type: ignore[arg-type]
    )
    official = CrossingRecord(
        crossing_id="shang-jiadong",
        name="上茄苳",
        normalized_name="上茄苳",
        line="縱貫線北段",
        km_marker="K308+845",
        km_prefix="",
        km_value_meters=308845,
        road_type="村里道路",
        station_pair_text="南靖-後壁",
        station_a_name="南靖",
        station_b_name="後壁",
        county="臺南市",
        source_page=29,
        source_row_index=3,
    )
    station_context = {
        "station_a_position": {"PositionLon": 120.401, "PositionLat": 23.436},
        "station_b_position": {"PositionLon": 120.359, "PositionLat": 23.363},
        "station_span_meters": 5877.0,
    }
    implausible_feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [120.3758451, 23.3884947]},
        "properties": {
            "osm_id": 2074462901,
            "normalized_name": "上茄苳平交道",
            "road_names": ["南91"],
            "rail_names": ["縱貫線"],
            "rail_way_ids": [321033991],
            "railway_position_meters": None,
        },
    }
    plausible_sibling_feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [120.3758178, 23.3884771]},
        "properties": {
            "osm_id": 3277482080,
            "normalized_name": "上茄苳平交道",
            "road_names": ["南91"],
            "rail_names": ["縱貫線"],
            "rail_way_ids": [321033995],
            "railway_position_meters": None,
        },
    }

    curated = catalog._build_curated_geojson(
        [official],
        {
            "type": "FeatureCollection",
            "features": [implausible_feature, plausible_sibling_feature],
        },
        station_context_lookup={official.crossing_id: station_context},
    )

    feature = curated["features"][0]
    assert curated["metadata"]["mapped_count"] == 1
    assert feature["properties"]["matched_osm_id"] == 3277482080
    assert feature["properties"]["match_method"] == "node_name"
    assert feature["geometry"]["coordinates"] == [120.3758178, 23.3884771]