from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.models.crossing import ConfidenceLevel


class PredictionSnapshotSource(BaseModel):
    source: Literal["liveboards", "timetables", "train_info"]
    complete: bool = True
    record_count: int = 0
    delayed_record_count: int = 0
    fetched_from: str | None = None
    cached_at: datetime | None = None
    scope: str | None = None
    detail: str | None = None


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
    previous_stop_station_id: str | None = None
    previous_stop_station_name: str | None = None
    previous_stop_departure: datetime | None = None
    next_stop_station_id: str | None = None
    next_stop_station_name: str | None = None
    next_stop_arrival: datetime | None = None
    upstream_station_id: str
    upstream_station_name: str
    downstream_station_id: str
    downstream_station_name: str
    eta: datetime
    warning: bool
    warning_window_minutes: int
    confidence: ConfidenceLevel
    confidence_reason: str | None = None
    delay_minutes: int = 0
    delay_source: Literal["train_info", "liveboard", "none"] | None = None
    data_basis: Literal["liveboard", "timetable"]
    prediction_method: str | None = None
    reason: str
    station_pair_source: str | None = None
    ratio_source: str | None = None
    segment_confidence: ConfidenceLevel | None = None
    segment_ratio: float = Field(ge=0.0, le=1.0)


class PredictionDataSnapshot(BaseModel):
    comprehensive: bool = True
    liveboard_count: int = 0
    delayed_liveboard_count: int = 0
    timetable_count: int = 0
    train_info_count: int = 0
    delayed_train_info_count: int = 0
    liveboard_scope: list[str] = Field(default_factory=list)
    sources: list[PredictionSnapshotSource] = Field(default_factory=list)
    timings_ms: dict[str, int] = Field(default_factory=dict)


class PredictionEnvelope(BaseModel):
    crossing_id: str
    generated_at: datetime
    warning_window_minutes: int
    horizon_minutes: int | None = None
    recent_window_minutes: int
    crossing: dict[str, Any] | None = None
    available: bool = True
    unavailable_reason: str | None = None
    unavailable_detail: str | None = None
    data_snapshot: PredictionDataSnapshot | None = None
    recent_prediction: PredictionRecord | None = None
    upcoming_predictions: list[PredictionRecord] = Field(default_factory=list)
    predictions: list[PredictionRecord] = Field(default_factory=list)
