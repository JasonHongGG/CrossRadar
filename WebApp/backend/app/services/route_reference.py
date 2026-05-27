from __future__ import annotations

import json
from functools import cached_property
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.models.crossing import CrossingRecord
from backend.app.utils import normalize_text


class RouteReferenceService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @cached_property
    def _payload(self) -> dict[str, Any]:
        path = self.settings.route_reference_json_path
        if not path.exists():
            return {"metadata": {}, "rules": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def metadata(self) -> dict[str, Any]:
        return dict(self._payload.get("metadata", {}))

    def apply(self, record: CrossingRecord) -> CrossingRecord:
        updated = record.model_copy(deep=True)
        updated.query_station_pair_text = updated.query_station_pair_text or updated.station_pair_text
        updated.query_station_a_name = updated.query_station_a_name or updated.station_a_name
        updated.query_station_b_name = updated.query_station_b_name or updated.station_b_name

        for rule in self._payload.get("rules", []):
            if not self._matches(rule.get("match", {}), updated):
                continue

            override = rule.get("override", {})
            updated.station_pair_text = override.get("station_pair_text") or updated.station_pair_text
            updated.station_a_name = override.get("station_a_name") or updated.station_a_name
            updated.station_b_name = override.get("station_b_name") or updated.station_b_name
            updated.station_pair_source = rule.get("pair_source") or "authoritative_reference"
            updated.station_pair_reference_id = rule.get("id") or updated.station_pair_reference_id
            updated.station_pair_reference_note = rule.get("reference_note") or updated.station_pair_reference_note
            updated.authoritative_reference_applied = True

            station_a_route_km = override.get("station_a_route_km_meters")
            if station_a_route_km is not None:
                updated.station_a_route_km_meters = int(station_a_route_km)
            station_b_route_km = override.get("station_b_route_km_meters")
            if station_b_route_km is not None:
                updated.station_b_route_km_meters = int(station_b_route_km)
            if override.get("station_route_reference_note"):
                updated.station_route_reference_note = override["station_route_reference_note"]
            segment_ratio_override = override.get("segment_ratio_override")
            if segment_ratio_override is not None:
                updated.segment_ratio_override = float(segment_ratio_override)
            if override.get("segment_ratio_override_source"):
                updated.segment_ratio_override_source = str(override["segment_ratio_override_source"])
            if override.get("segment_ratio_override_confidence"):
                updated.segment_ratio_override_confidence = str(override["segment_ratio_override_confidence"])
            if override.get("segment_ratio_override_note"):
                updated.segment_ratio_override_note = override["segment_ratio_override_note"]

        return updated

    def _matches(self, match: dict[str, Any], record: CrossingRecord) -> bool:
        county = match.get("county")
        if county and normalize_text(record.county) != normalize_text(county):
            return False

        line = match.get("line")
        if line and normalize_text(record.line) != normalize_text(line):
            return False

        name = match.get("name")
        if name and normalize_text(record.name) != normalize_text(name):
            return False

        crossing_id = match.get("crossing_id")
        if crossing_id and record.crossing_id != crossing_id:
            return False

        km_value_meters = match.get("km_value_meters")
        if km_value_meters is not None and record.km_value_meters != int(km_value_meters):
            return False

        km_range = match.get("km_range", {})
        if km_range:
            km_value = record.km_value_meters
            if km_value is None:
                return False
            lower = km_range.get("gte")
            if lower is not None and km_value < int(lower):
                return False
            upper = km_range.get("lt")
            if upper is not None and km_value >= int(upper):
                return False

        return True