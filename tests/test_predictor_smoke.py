from __future__ import annotations

from datetime import date

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
