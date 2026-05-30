from __future__ import annotations

import json
from datetime import date, timedelta

from backend.app.config import get_settings
from backend.app.models.prediction import PredictionRecord
from backend.app.services.prediction_calibration import PredictionCalibrationService
from backend.app.services.predictor import PredictorService
from backend.app.services.travel_profile import TravelProfileService
from backend.app.utils import parse_time_on_date


def test_parse_time_on_date_smoke() -> None:
    parsed = parse_time_on_date(date(2026, 5, 20), "12:34:56")
    assert parsed is not None
    assert parsed.hour == 12
    assert parsed.minute == 34


def test_parse_time_on_date_without_seconds() -> None:
    parsed = parse_time_on_date(date(2026, 5, 20), "09:36")
    assert parsed is not None
    assert parsed.hour == 9
    assert parsed.minute == 36


def test_prediction_confidence_rules() -> None:
    predictor = PredictorService.__new__(PredictorService)
    assert predictor._prediction_confidence("high", has_liveboard=True) == "high"
    assert predictor._prediction_confidence("medium", has_liveboard=False) == "medium"
    assert predictor._prediction_confidence("low", has_liveboard=True) == "low"


def test_prediction_confidence_reason_mentions_pair_and_ratio_sources() -> None:
    predictor = PredictorService.__new__(PredictorService)
    reason = predictor._prediction_confidence_reason(
        {
            "station_pair_source": "authoritative_reference",
            "ratio_source": "osm_path",
            "segment_confidence_reason": "Used OSM rail geometry.",
        },
        has_liveboard=False,
    )

    assert "authoritative_reference" in reason
    assert "osm_path" in reason
    assert "Used OSM rail geometry." in reason


def test_reverse_direction_eta_preserves_crossing_order() -> None:
    predictor = PredictorService.__new__(PredictorService)
    upstream_departure = parse_time_on_date(date(2026, 5, 20), "10:00")
    downstream_arrival = parse_time_on_date(date(2026, 5, 20), "10:10")
    assert upstream_departure is not None
    assert downstream_arrival is not None

    north_crossing = {
        "station_a_id": "YONGKANG",
        "station_b_id": "TAINAN",
        "segment_ratio": 0.3,
        "ratio_source": "osm_path",
    }
    south_crossing = {
        "station_a_id": "YONGKANG",
        "station_b_id": "TAINAN",
        "segment_ratio": 0.7,
        "ratio_source": "osm_path",
    }

    north_eta, north_ratio = predictor._estimate_crossing_eta(
        north_crossing,
        upstream_station_id="TAINAN",
        downstream_station_id="YONGKANG",
        upstream_departure=upstream_departure,
        downstream_arrival=downstream_arrival,
    )
    south_eta, south_ratio = predictor._estimate_crossing_eta(
        south_crossing,
        upstream_station_id="TAINAN",
        downstream_station_id="YONGKANG",
        upstream_departure=upstream_departure,
        downstream_arrival=downstream_arrival,
    )

    assert south_ratio < north_ratio
    assert south_eta < north_eta


def test_skip_stop_eta_uses_actual_stop_pair_osm_projection() -> None:
    predictor = PredictorService.__new__(PredictorService)
    expected_ratio = 0.19

    class _StubStationGraphService:
        def resolve_runtime_ratio_for_station_pair(self, crossing, **kwargs):  # noqa: ANN001
            return (expected_ratio, "osm_path", "high", "stubbed stop-pair path")

    predictor.station_graph_service = _StubStationGraphService()
    crossing = {
        "station_a_id": "YONGKANG",
        "station_b_id": "TAINAN",
        "segment_ratio": 0.3273477076302729,
        "ratio_source": "osm_path",
        "segment_confidence": "medium",
        "segment_confidence_reason": "test",
        "geometry": {"lon": 120.2371122, "lat": 23.0277097},
    }
    station_lookup_by_id = {
        "TAINAN": {"StationPosition": {"PositionLat": 22.99681, "PositionLon": 120.21295}},
        "XINYING": {"StationPosition": {"PositionLat": 23.30531, "PositionLon": 120.31755}},
    }

    ratio, ratio_source, segment_confidence, _ = predictor._prediction_segment_context(
        crossing,
        upstream_station_id="TAINAN",
        downstream_station_id="XINYING",
        station_lookup_by_id=station_lookup_by_id,
    )

    assert ratio == expected_ratio
    assert ratio != crossing["segment_ratio"]
    assert ratio_source == "osm_path"
    assert segment_confidence == "high"


def test_non_anchor_osm_projection_is_accepted_for_prediction_segment() -> None:
    predictor = PredictorService.__new__(PredictorService)

    assert predictor._is_prediction_segment_valid(
        {
            "station_a_id": "YONGKANG",
            "station_b_id": "TAINAN",
        },
        upstream_station_id="TAINAN",
        downstream_station_id="XINYING",
        ratio=0.19,
        ratio_source="osm_path",
    ) is True


def test_resolve_delay_minutes_prefers_train_info_over_liveboard() -> None:
    predictor = PredictorService.__new__(PredictorService)

    delay_minutes, delay_source = predictor._resolve_delay_minutes(
        "3001",
        liveboard={"DelayTime": 2},
        train_info_by_train_no={"3001": {"DelayTime": 7}},
    )

    assert delay_minutes == 7
    assert delay_source == "train_info"


def test_dedupe_liveboards_keeps_station_context() -> None:
    predictor = PredictorService.__new__(PredictorService)
    liveboards = [
        {"TrainNo": "3001", "StationID": "A", "UpdateTime": "2026-05-28T10:00:00+08:00", "DelayTime": 1},
        {"TrainNo": "3001", "StationID": "A", "UpdateTime": "2026-05-28T10:00:00+08:00", "DelayTime": 1},
        {"TrainNo": "3001", "StationID": "B", "UpdateTime": "2026-05-28T10:00:00+08:00", "DelayTime": 1},
    ]

    deduped = predictor._dedupe_liveboards(liveboards)

    assert len(deduped) == 2
    assert {record["StationID"] for record in deduped} == {"A", "B"}


def test_dedupe_liveboards_keeps_freshest_record_per_station() -> None:
    predictor = PredictorService.__new__(PredictorService)
    liveboards = [
        {"TrainNo": "3001", "StationID": "A", "UpdateTime": "2026-05-28T10:00:00+08:00", "DelayTime": 1},
        {"TrainNo": "3001", "StationID": "A", "UpdateTime": "2026-05-28T10:02:00+08:00", "DelayTime": 3},
    ]

    deduped = predictor._dedupe_liveboards(liveboards)

    assert len(deduped) == 1
    assert deduped[0]["DelayTime"] == 3


def test_select_best_timetable_prefers_exact_anchor_pair() -> None:
    predictor = PredictorService.__new__(PredictorService)
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.03825, "PositionLon": 120.25347}},
        "B": {"StationPosition": {"PositionLat": 22.99681, "PositionLon": 120.21295}},
        "X": {"StationPosition": {"PositionLat": 23.30531, "PositionLon": 120.31755}},
    }
    single_anchor = {
        "StopTimes": [
            {"StopSequence": 1, "StationID": "X", "StationName": {"Zh_tw": "新營"}},
            {"StopSequence": 2, "StationID": "B", "StationName": {"Zh_tw": "臺南"}},
        ]
    }
    exact = {
        "StopTimes": [
            {"StopSequence": 5, "StationID": "A", "StationName": {"Zh_tw": "永康"}},
            {"StopSequence": 6, "StationID": "B", "StationName": {"Zh_tw": "臺南"}},
        ]
    }

    selected = predictor._select_best_timetable(
        [single_anchor, exact],
        "A",
        "B",
        station_lookup_by_id=station_lookup_by_id,
    )

    assert selected is exact


def test_build_predictions_from_timetables_applies_train_info_delay() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date.today(), "09:30")
    assert now is not None

    crossing = {
        "station_a_id": "A",
        "station_b_id": "B",
        "segment_ratio": 0.5,
        "ratio_source": "osm_path",
        "geolocation_confidence": "high",
        "segment_confidence": "high",
    }
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.0, "PositionLon": 120.0}},
        "B": {"StationPosition": {"PositionLat": 22.9, "PositionLon": 120.1}},
    }
    timetables = [
        {
            "TrainInfo": {
                "TrainNo": "3001",
                "TrainTypeName": {"Zh_tw": "區間"},
                "StartingStationID": "A",
                "StartingStationName": {"Zh_tw": "甲站"},
                "EndingStationID": "B",
                "EndingStationName": {"Zh_tw": "乙站"},
            },
            "StopTimes": [
                {
                    "StopSequence": 1,
                    "StationID": "A",
                    "StationName": {"Zh_tw": "甲站"},
                    "ArrivalTime": "10:00",
                    "DepartureTime": "10:00",
                },
                {
                    "StopSequence": 2,
                    "StationID": "B",
                    "StationName": {"Zh_tw": "乙站"},
                    "ArrivalTime": "10:10",
                    "DepartureTime": "10:10",
                },
            ],
        }
    ]

    predictions = predictor._build_predictions_from_timetables(
        crossing,
        timetables,
        train_info_by_train_no={"3001": {"DelayTime": 4}},
        station_lookup_by_id=station_lookup_by_id,
        now=now,
        horizon_minutes=None,
        recent_minutes=10,
        warning_minutes=5,
    )

    assert len(predictions) == 1
    assert predictions[0].delay_minutes == 4
    assert predictions[0].delay_source == "train_info"
    assert predictions[0].previous_stop_departure == parse_time_on_date(date.today(), "10:04")
    assert predictions[0].next_stop_arrival == parse_time_on_date(date.today(), "10:14")


def test_timetable_predictions_can_use_liveboard_delay_only_fallback() -> None:
    predictor = PredictorService.__new__(PredictorService)

    class _StubStationGraphService:
        def resolve_runtime_ratio_for_station_pair(self, crossing, **kwargs):  # noqa: ANN001
            return (None, "unavailable", "low", "no projection")

    predictor.station_graph_service = _StubStationGraphService()
    now = parse_time_on_date(date.today(), "09:30")
    assert now is not None

    crossing = {
        "station_a_id": "A",
        "station_b_id": "B",
        "segment_ratio": 0.5,
        "ratio_source": "osm_path",
        "geolocation_confidence": "high",
        "segment_confidence": "high",
    }
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.0, "PositionLon": 120.0}},
        "B": {"StationPosition": {"PositionLat": 22.9, "PositionLon": 120.1}},
    }
    timetables = [
        {
            "TrainInfo": {
                "TrainNo": "3001",
                "TrainTypeName": {"Zh_tw": "區間"},
                "StartingStationID": "A",
                "StartingStationName": {"Zh_tw": "甲站"},
                "EndingStationID": "B",
                "EndingStationName": {"Zh_tw": "乙站"},
            },
            "StopTimes": [
                {
                    "StopSequence": 1,
                    "StationID": "A",
                    "StationName": {"Zh_tw": "甲站"},
                    "ArrivalTime": "10:00",
                    "DepartureTime": "10:00",
                },
                {
                    "StopSequence": 2,
                    "StationID": "B",
                    "StationName": {"Zh_tw": "乙站"},
                    "ArrivalTime": "10:10",
                    "DepartureTime": "10:10",
                },
            ],
        }
    ]
    liveboards = [
        {
            "TrainNo": "3001",
            "StationID": "B",
            "StationName": {"Zh_tw": "乙站"},
            "TrainTypeName": {"Zh_tw": "區間"},
            "UpdateTime": f"{date.today().isoformat()}T10:10:00+08:00",
            "DelayTime": 1,
        }
    ]
    prepared = predictor._prepare_timetables_for_crossing(
        timetables,
        "A",
        "B",
        station_lookup_by_id=station_lookup_by_id,
    )
    fallback_reasons: dict[str, str] = {}
    fallback_delays = {}
    fallback_liveboards = {}

    live_predictions = predictor._build_predictions_from_liveboards(
        crossing,
        liveboards,
        timetables,
        prepared_timetables=prepared,
        train_info_by_train_no={},
        station_lookup_by_id=station_lookup_by_id,
        now=now,
        horizon_minutes=None,
        recent_minutes=10,
        warning_minutes=5,
        fallback_reasons_by_train_no=fallback_reasons,
        fallback_delays_by_train_no=fallback_delays,
        fallback_liveboards_by_train_no=fallback_liveboards,
    )

    assert live_predictions == []
    assert fallback_delays["3001"].source == "liveboard"
    assert fallback_delays["3001"].minutes == 1
    assert "3001" in fallback_reasons

    predictions = predictor._build_predictions_from_timetables(
        crossing,
        timetables,
        prepared_timetables=prepared,
        train_info_by_train_no={},
        station_lookup_by_id=station_lookup_by_id,
        now=now,
        horizon_minutes=None,
        recent_minutes=10,
        warning_minutes=5,
        liveboard_fallback_reasons_by_train_no=fallback_reasons,
        liveboard_fallback_delays_by_train_no=fallback_delays,
        liveboard_fallback_liveboards_by_train_no=fallback_liveboards,
    )

    assert len(predictions) == 1
    assert predictions[0].delay_source == "liveboard"
    assert predictions[0].delay_minutes == 1
    assert predictions[0].source_station_id == "B"
    assert "liveboard delay fallback" in predictions[0].reason


def test_build_predictions_from_liveboards_uses_observed_stop_delay_before_crossing() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date.today(), "09:50")
    assert now is not None

    crossing = {
        "station_a_id": "A",
        "station_b_id": "B",
        "segment_ratio": 0.5,
        "ratio_source": "osm_path",
        "geolocation_confidence": "high",
        "segment_confidence": "high",
    }
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.0, "PositionLon": 120.0}},
        "B": {"StationPosition": {"PositionLat": 22.9, "PositionLon": 120.1}},
        "X": {"StationPosition": {"PositionLat": 23.05, "PositionLon": 120.05}},
    }
    timetables = [
        {
            "TrainInfo": {
                "TrainNo": "3001",
                "TrainTypeName": {"Zh_tw": "區間"},
                "StartingStationID": "X",
                "StartingStationName": {"Zh_tw": "前站"},
                "EndingStationID": "B",
                "EndingStationName": {"Zh_tw": "乙站"},
            },
            "StopTimes": [
                {
                    "StopSequence": 1,
                    "StationID": "X",
                    "StationName": {"Zh_tw": "前站"},
                    "ArrivalTime": "09:55",
                    "DepartureTime": "09:55",
                },
                {
                    "StopSequence": 2,
                    "StationID": "A",
                    "StationName": {"Zh_tw": "甲站"},
                    "ArrivalTime": "10:00",
                    "DepartureTime": "10:00",
                },
                {
                    "StopSequence": 3,
                    "StationID": "B",
                    "StationName": {"Zh_tw": "乙站"},
                    "ArrivalTime": "10:10",
                    "DepartureTime": "10:10",
                },
            ],
        }
    ]
    liveboards = [
        {
            "TrainNo": "3001",
            "StationID": "X",
            "StationName": {"Zh_tw": "前站"},
            "TrainTypeName": {"Zh_tw": "區間"},
            "UpdateTime": f"{date.today().isoformat()}T09:57:00+08:00",
            "DelayTime": 0,
        }
    ]

    predictions = predictor._build_predictions_from_liveboards(
        crossing,
        liveboards,
        timetables,
        train_info_by_train_no={"3001": {"DelayTime": 0}},
        station_lookup_by_id=station_lookup_by_id,
        now=now,
        horizon_minutes=None,
        recent_minutes=10,
        warning_minutes=5,
    )

    assert len(predictions) == 1
    assert predictions[0].source_station_id == "X"
    assert predictions[0].delay_source == "liveboard"
    assert predictions[0].delay_seconds == 120
    assert predictions[0].previous_stop_departure == parse_time_on_date(date.today(), "10:02")


def test_build_predictions_from_liveboards_uses_projected_pass_through_station_delay() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date.today(), "09:55")
    assert now is not None

    class _StubStationGraphService:
        def resolve_runtime_ratio_for_station_pair(self, crossing, **kwargs):  # noqa: ANN001
            geometry = crossing.get("geometry") or {}
            if geometry.get("lon") == 120.05:
                return (0.5, "osm_path", "high", "stubbed pass-through station")
            return (None, "unavailable", "low", "no projection")

    predictor.station_graph_service = _StubStationGraphService()
    crossing = {
        "station_a_id": "A",
        "station_b_id": "B",
        "segment_ratio": 0.8,
        "ratio_source": "osm_path",
        "geolocation_confidence": "high",
        "segment_confidence": "high",
        "geometry": {"lon": 120.08, "lat": 23.0},
        "osm_rail_way_ids": [1],
    }
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.0, "PositionLon": 120.0}},
        "B": {"StationPosition": {"PositionLat": 23.0, "PositionLon": 120.1}},
        "L": {"StationPosition": {"PositionLat": 23.0, "PositionLon": 120.05}},
    }
    timetables = [
        {
            "TrainInfo": {
                "TrainNo": "3002",
                "TrainTypeName": {"Zh_tw": "區間"},
                "StartingStationID": "A",
                "StartingStationName": {"Zh_tw": "甲站"},
                "EndingStationID": "B",
                "EndingStationName": {"Zh_tw": "乙站"},
            },
            "StopTimes": [
                {
                    "StopSequence": 1,
                    "StationID": "A",
                    "StationName": {"Zh_tw": "甲站"},
                    "ArrivalTime": "10:00",
                    "DepartureTime": "10:00",
                },
                {
                    "StopSequence": 2,
                    "StationID": "B",
                    "StationName": {"Zh_tw": "乙站"},
                    "ArrivalTime": "10:10",
                    "DepartureTime": "10:10",
                },
            ],
        }
    ]
    liveboards = [
        {
            "TrainNo": "3002",
            "StationID": "L",
            "StationName": {"Zh_tw": "通過站"},
            "TrainTypeName": {"Zh_tw": "區間"},
            "UpdateTime": f"{date.today().isoformat()}T10:06:00+08:00",
            "DelayTime": 0,
        }
    ]

    predictions = predictor._build_predictions_from_liveboards(
        crossing,
        liveboards,
        timetables,
        train_info_by_train_no={"3002": {"DelayTime": 0}},
        station_lookup_by_id=station_lookup_by_id,
        now=now,
        horizon_minutes=None,
        recent_minutes=10,
        warning_minutes=5,
    )

    assert len(predictions) == 1
    assert predictions[0].source_station_id == "L"
    assert predictions[0].delay_source == "liveboard"
    assert predictions[0].delay_seconds == 60
    assert predictions[0].previous_stop_departure == parse_time_on_date(date.today(), "10:01")


def test_partition_predictions_keeps_recent_past_and_next_two_upcoming() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date(2026, 5, 20), "10:00")
    assert now is not None

    def build_prediction(train_no: str, offset_minutes: int) -> PredictionRecord:
        eta = now + timedelta(minutes=offset_minutes)
        return PredictionRecord(
            train_no=train_no,
            upstream_station_id="A",
            upstream_station_name="甲站",
            downstream_station_id="B",
            downstream_station_name="乙站",
            eta=eta,
            warning=offset_minutes >= 0 and offset_minutes <= 5,
            warning_window_minutes=5,
            confidence="medium",
            data_basis="timetable",
            reason="test",
            segment_ratio=0.5,
        )

    predictions = [
        build_prediction("1001", -12),
        build_prediction("1002", -3),
        build_prediction("1003", 2),
        build_prediction("1004", 7),
        build_prediction("1005", 11),
    ]

    recent_prediction, upcoming_predictions, all_upcoming_predictions = predictor._partition_predictions(
        predictions,
        now=now,
        recent_minutes=10,
    )

    assert recent_prediction is not None
    assert recent_prediction.train_no == "1002"
    assert [record.train_no for record in upcoming_predictions] == ["1003", "1004"]
    assert [record.train_no for record in all_upcoming_predictions] == ["1003", "1004", "1005"]


def test_prediction_window_without_horizon_keeps_far_future_train() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date(2026, 5, 20), "10:00")
    eta = parse_time_on_date(date(2026, 5, 20), "18:30")

    assert now is not None
    assert eta is not None
    assert predictor._is_prediction_in_window(
        eta,
        now=now,
        horizon_minutes=None,
        recent_minutes=10,
    ) is True


def test_merge_predictions_keeps_live_and_missing_timetable_trains() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date(2026, 5, 20), "10:00")
    assert now is not None

    def build_prediction(
        train_no: str,
        offset_minutes: int,
        *,
        data_basis: str,
        upstream_station_id: str = "A",
        downstream_station_id: str = "B",
    ) -> PredictionRecord:
        eta = now + timedelta(minutes=offset_minutes)
        return PredictionRecord(
            train_no=train_no,
            upstream_station_id=upstream_station_id,
            upstream_station_name="甲站",
            downstream_station_id=downstream_station_id,
            downstream_station_name="乙站",
            eta=eta,
            warning=False,
            warning_window_minutes=5,
            confidence="medium",
            data_basis=data_basis,  # type: ignore[arg-type]
            reason="test",
            segment_ratio=0.5,
        )

    live_predictions = [build_prediction("3023", 2, data_basis="liveboard")]
    timetable_predictions = [
        build_prediction("3023", 1, data_basis="timetable"),
        build_prediction("125", 8, data_basis="timetable", upstream_station_id="X", downstream_station_id="B"),
        build_prediction("3757", 15, data_basis="timetable"),
    ]

    merged = predictor._merge_predictions(live_predictions, timetable_predictions)

    assert [record.train_no for record in merged] == ["3023", "125", "3757"]
    assert merged[0].data_basis == "liveboard"


def test_resolve_stop_pair_uses_single_anchor_neighbor_toward_other_anchor() -> None:
    predictor = PredictorService.__new__(PredictorService)
    timetable = {
        "StopTimes": [
            {
                "StopSequence": 18,
                "StationID": "X",
                "StationName": {"Zh_tw": "新營"},
                "ArrivalTime": "16:50",
                "DepartureTime": "16:52",
            },
            {
                "StopSequence": 19,
                "StationID": "B",
                "StationName": {"Zh_tw": "臺南"},
                "ArrivalTime": "17:16",
                "DepartureTime": "17:18",
            },
            {
                "StopSequence": 20,
                "StationID": "Y",
                "StationName": {"Zh_tw": "保安"},
                "ArrivalTime": "17:26",
                "DepartureTime": "17:27",
            },
        ]
    }
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.03825, "PositionLon": 120.25347}},
        "B": {"StationPosition": {"PositionLat": 22.99681, "PositionLon": 120.21295}},
        "X": {"StationPosition": {"PositionLat": 23.30531, "PositionLon": 120.31755}},
        "Y": {"StationPosition": {"PositionLat": 22.93814, "PositionLon": 120.22977}},
    }

    pair = predictor._resolve_stop_pair(
        timetable,
        "A",
        "B",
        station_lookup_by_id=station_lookup_by_id,
    )

    assert pair is not None
    upstream, downstream, direction = pair
    assert upstream["StationID"] == "X"
    assert downstream["StationID"] == "B"
    assert direction == 0


def test_resolve_stop_pair_rejects_single_anchor_neighbor_away_from_other_anchor() -> None:
    predictor = PredictorService.__new__(PredictorService)
    timetable = {
        "StopTimes": [
            {
                "StopSequence": 19,
                "StationID": "B",
                "StationName": {"Zh_tw": "臺南"},
                "ArrivalTime": "17:16",
                "DepartureTime": "17:18",
            },
            {
                "StopSequence": 20,
                "StationID": "Y",
                "StationName": {"Zh_tw": "保安"},
                "ArrivalTime": "17:26",
                "DepartureTime": "17:27",
            },
        ]
    }
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.03825, "PositionLon": 120.25347}},
        "B": {"StationPosition": {"PositionLat": 22.99681, "PositionLon": 120.21295}},
        "Y": {"StationPosition": {"PositionLat": 22.93814, "PositionLon": 120.22977}},
    }

    pair = predictor._resolve_stop_pair(
        timetable,
        "A",
        "B",
        station_lookup_by_id=station_lookup_by_id,
    )

    assert pair is None


def test_build_predictions_from_timetables_skips_non_bracketing_single_anchor_pair() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date.today(), "03:47")
    assert now is not None

    crossing = {
        "station_a_id": "A",
        "station_b_id": "B",
        "segment_ratio": 0.31607606206598104,
        "geolocation_confidence": "high",
        "segment_confidence": "high",
        "geometry": {"lon": 120.2371122, "lat": 23.0277097},
    }
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.03825, "PositionLon": 120.25347}},
        "B": {"StationPosition": {"PositionLat": 22.99681, "PositionLon": 120.21295}},
        "Y": {"StationPosition": {"PositionLat": 22.93814, "PositionLon": 120.22977}},
    }
    timetables = [
        {
            "TrainInfo": {
                "TrainNo": "3701",
                "TrainTypeName": {"Zh_tw": "區間"},
                "StartingStationID": "B",
                "StartingStationName": {"Zh_tw": "臺南"},
                "EndingStationID": "Y",
                "EndingStationName": {"Zh_tw": "保安"},
            },
            "StopTimes": [
                {
                    "StopSequence": 1,
                    "StationID": "B",
                    "StationName": {"Zh_tw": "臺南"},
                    "ArrivalTime": "05:29",
                    "DepartureTime": "05:29",
                },
                {
                    "StopSequence": 2,
                    "StationID": "Y",
                    "StationName": {"Zh_tw": "保安"},
                    "ArrivalTime": "05:36",
                    "DepartureTime": "05:36",
                },
            ],
        }
    ]

    predictions = predictor._build_predictions_from_timetables(
        crossing,
        timetables,
        station_lookup_by_id=station_lookup_by_id,
        now=now,
        horizon_minutes=None,
        recent_minutes=10,
        warning_minutes=5,
    )

    assert predictions == []


def test_build_predictions_from_timetables_keeps_all_sorted_candidates() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date.today(), "10:00")
    assert now is not None

    crossing = {
        "station_a_id": "A",
        "station_b_id": "B",
        "segment_ratio": 0.5,
        "ratio_source": "osm_path",
        "geolocation_confidence": "high",
        "segment_confidence": "high",
    }
    station_lookup_by_id = {
        "A": {"StationPosition": {"PositionLat": 23.0, "PositionLon": 120.0}},
        "B": {"StationPosition": {"PositionLat": 22.9, "PositionLon": 120.1}},
    }

    def build_timetable(train_no: str, minute_offset: int) -> dict:
        departure = now + timedelta(minutes=minute_offset)
        arrival = departure + timedelta(minutes=6)
        return {
            "TrainInfo": {
                "TrainNo": train_no,
                "TrainTypeName": {"Zh_tw": "區間"},
                "StartingStationID": "A",
                "StartingStationName": {"Zh_tw": "甲站"},
                "EndingStationID": "B",
                "EndingStationName": {"Zh_tw": "乙站"},
            },
            "StopTimes": [
                {
                    "StopSequence": 1,
                    "StationID": "A",
                    "StationName": {"Zh_tw": "甲站"},
                    "ArrivalTime": departure.strftime("%H:%M"),
                    "DepartureTime": departure.strftime("%H:%M"),
                },
                {
                    "StopSequence": 2,
                    "StationID": "B",
                    "StationName": {"Zh_tw": "乙站"},
                    "ArrivalTime": arrival.strftime("%H:%M"),
                    "DepartureTime": arrival.strftime("%H:%M"),
                },
            ],
        }

    timetables = [build_timetable(f"10{index:02d}", index) for index in range(11)]

    predictions = predictor._build_predictions_from_timetables(
        crossing,
        timetables,
        station_lookup_by_id=station_lookup_by_id,
        now=now,
        horizon_minutes=120,
        recent_minutes=10,
        warning_minutes=5,
    )

    assert len(predictions) == 11
    assert [record.train_no for record in predictions[:3]] == ["1000", "1001", "1002"]


def test_travel_profile_biases_stop_to_stop_time_fraction() -> None:
    service = TravelProfileService()

    early = service.estimate(
        ratio=0.2,
        train_type_name="區間",
        upstream_dwell_seconds=30,
        downstream_dwell_seconds=30,
    )
    late = service.estimate(
        ratio=0.8,
        train_type_name="區間",
        upstream_dwell_seconds=30,
        downstream_dwell_seconds=30,
    )

    assert early.time_fraction > 0.2
    assert late.time_fraction < 0.8


def test_estimate_prediction_timing_applies_liveboard_anchor_and_calibration(tmp_path) -> None:
    calibration_path = tmp_path / "prediction_calibration.json"
    calibration_path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "id": "demo-rule",
                        "match": {
                            "crossing_id": "demo-crossing",
                            "direction": 1,
                            "upstream_station_id": "A",
                            "train_type_family": "local",
                        },
                        "offset_seconds": 45,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings = get_settings().model_copy(update={"prediction_calibration_path": calibration_path})

    predictor = PredictorService.__new__(PredictorService)
    predictor.travel_profile_service = TravelProfileService()
    predictor.prediction_calibration_service = PredictionCalibrationService(predictor.travel_profile_service, settings)

    upstream_departure = parse_time_on_date(date(2026, 5, 28), "10:00")
    downstream_arrival = parse_time_on_date(date(2026, 5, 28), "10:10")
    expected_eta = parse_time_on_date(date(2026, 5, 28), "10:07:45")
    assert upstream_departure is not None
    assert downstream_arrival is not None
    assert expected_eta is not None

    timing = predictor._estimate_prediction_timing(
        {
            "id": "demo-crossing",
            "station_a_id": "A",
            "station_b_id": "B",
            "segment_ratio": 0.5,
            "ratio_source": "osm_path",
            "segment_confidence": "high",
        },
        train_no="3001",
        train_type_name="區間",
        upstream_station_id="A",
        downstream_station_id="B",
        upstream={"StationID": "A", "ArrivalTime": "10:00", "DepartureTime": "10:00"},
        downstream={"StationID": "B", "ArrivalTime": "10:10", "DepartureTime": "10:10"},
        upstream_departure=upstream_departure,
        downstream_arrival=downstream_arrival,
        delay_minutes=0,
        delay_source="none",
        direction=1,
        liveboard={"StationID": "A", "UpdateTime": "2026-05-28T10:02:00+08:00"},
        data_basis="liveboard",
    )

    assert timing is not None
    assert timing.anchor_time_source == "liveboard_update"
    assert timing.calibration_offset_seconds == 45
    assert timing.accuracy_tier == "high"
    assert timing.eta == expected_eta
