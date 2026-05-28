from __future__ import annotations

import json
from functools import cached_property
from typing import Any

from backend.app.config import Settings, get_settings
from backend.app.services.travel_profile import TravelProfileService


class PredictionCalibrationService:
    def __init__(
        self,
        travel_profile_service: TravelProfileService,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.travel_profile_service = travel_profile_service

    @cached_property
    def _payload(self) -> dict[str, Any]:
        path = self.settings.prediction_calibration_path
        if not path.exists():
            return {"metadata": {}, "baseline": {}, "rules": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"metadata": {}, "baseline": {}, "rules": []}

    def metadata(self) -> dict[str, Any]:
        return dict(self._payload.get("metadata", {}))

    def lookup_offset_seconds(
        self,
        *,
        crossing_id: str,
        direction: int | None,
        train_type_name: str | None,
        upstream_station_id: str | None = None,
    ) -> tuple[int, str | None]:
        family = self.travel_profile_service.classify_train_type_family(train_type_name)
        for rule in self._payload.get("rules", []):
            match = rule.get("match", {})
            if match.get("crossing_id") not in (None, crossing_id):
                continue
            if match.get("direction") not in (None, direction):
                continue
            if match.get("train_type_family") not in (None, family):
                continue
            if match.get("upstream_station_id") not in (None, upstream_station_id):
                continue
            return (int(rule.get("offset_seconds") or 0), str(rule.get("id") or "") or None)
        return (0, None)