from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.models.crossing import ConfidenceLevel


class PredictionRecord(BaseModel):
    train_no: str
    train_type: str | None = None
    direction: int | None = None
    headsign: str | None = None
    origin_station_id: str | None = None
    origin_station_name: str | None = None
    destination_station_id: str | None = None
    destination_station_name: str | None = None
    source_station_id: str | None = None
    source_station_name: str | None = None
    upstream_station_id: str
    upstream_station_name: str
    downstream_station_id: str
    downstream_station_name: str
    eta: datetime
    warning: bool
    warning_window_minutes: int
    confidence: ConfidenceLevel
    delay_minutes: int = 0
    data_basis: Literal["liveboard", "timetable"]
    reason: str
    segment_ratio: float = Field(ge=0.0, le=1.0)


class PredictionEnvelope(BaseModel):
    crossing_id: str
    generated_at: datetime
    warning_window_minutes: int
    horizon_minutes: int
    recent_window_minutes: int
    recent_prediction: PredictionRecord | None = None
    upcoming_predictions: list[PredictionRecord] = Field(default_factory=list)
    predictions: list[PredictionRecord]
