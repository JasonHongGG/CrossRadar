from __future__ import annotations

from datetime import date, timedelta

from backend.app.models.prediction import PredictionRecord
from backend.app.services.predictor import PredictorService
from backend.app.utils import parse_time_on_date, point_ratio_between_stations


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
    }
    south_crossing = {
        "station_a_id": "YONGKANG",
        "station_b_id": "TAINAN",
        "segment_ratio": 0.7,
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


def test_skip_stop_eta_uses_actual_stop_pair_projection() -> None:
    predictor = PredictorService.__new__(PredictorService)
    crossing = {
        "station_a_id": "YONGKANG",
        "station_b_id": "TAINAN",
        "segment_ratio": 0.3273477076302729,
        "ratio_source": "geometry_projection",
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

    expected_ratio = point_ratio_between_stations(
        120.21295,
        22.99681,
        120.31755,
        23.30531,
        120.2371122,
        23.0277097,
    )

    assert ratio == expected_ratio
    assert ratio != crossing["segment_ratio"]
    assert ratio_source == "geometry_projection"
    assert segment_confidence == "medium"


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


def test_build_predictions_from_timetables_keeps_all_sorted_candidates() -> None:
    predictor = PredictorService.__new__(PredictorService)
    now = parse_time_on_date(date.today(), "10:00")
    assert now is not None

    crossing = {
        "station_a_id": "A",
        "station_b_id": "B",
        "segment_ratio": 0.5,
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
