from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ConfidenceLevel = Literal["high", "medium", "low"]


class GeoPoint(BaseModel):
    lat: float
    lon: float


class CrossingRecord(BaseModel):
    crossing_id: str
    name: str
    normalized_name: str
    line: str
    km_marker: str | None = None
    km_prefix: str | None = None
    km_value_meters: int | None = None
    road_type: str | None = None
    station_pair_text: str | None = None
    station_a_name: str | None = None
    station_b_name: str | None = None
    county: str | None = None
    source_page: int
    source_row_index: int
    matched_osm_id: int | None = None
    match_score: float = 0.0
    match_method: str | None = None
    geolocation_confidence: ConfidenceLevel = "low"
    segment_confidence: ConfidenceLevel = "low"
    station_a_id: str | None = None
    station_b_id: str | None = None
    segment_ratio: float | None = None
    geometry: GeoPoint | None = None
    osm_road_names: list[str] = Field(default_factory=list)
    osm_rail_names: list[str] = Field(default_factory=list)
    osm_tags: dict[str, Any] = Field(default_factory=dict)

    def to_feature(self) -> dict[str, Any]:
        geometry = None
        if self.geometry is not None:
            geometry = {
                "type": "Point",
                "coordinates": [self.geometry.lon, self.geometry.lat],
            }
        return {
            "type": "Feature",
            "id": self.crossing_id,
            "geometry": geometry,
            "properties": self.model_dump(exclude={"geometry"}),
        }
