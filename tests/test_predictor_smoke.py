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
