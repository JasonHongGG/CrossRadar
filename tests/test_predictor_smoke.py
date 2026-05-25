from __future__ import annotations

from datetime import date, timedelta

from backend.app.models.prediction import PredictionRecord
from backend.app.services.predictor import PredictorService
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
