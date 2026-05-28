from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TravelProfile:
    profile_id: str
    accel_time_fraction: float
    decel_time_fraction: float
    base_uncertainty_seconds: int


@dataclass(frozen=True)
class TravelProfileEstimate:
    profile_id: str
    train_type_family: str
    time_fraction: float
    base_uncertainty_seconds: int


PROFILE_DEFAULTS: dict[tuple[str, str, str], TravelProfile] = {
    ("local", "from_stop", "to_stop"): TravelProfile("local-stop-stop", 0.18, 0.16, 45),
    ("local", "from_stop", "through"): TravelProfile("local-stop-through", 0.16, 0.05, 40),
    ("local", "through", "to_stop"): TravelProfile("local-through-stop", 0.05, 0.16, 40),
    ("local", "through", "through"): TravelProfile("local-through-through", 0.03, 0.03, 35),
    ("local_fast", "from_stop", "to_stop"): TravelProfile("local-fast-stop-stop", 0.15, 0.14, 42),
    ("local_fast", "from_stop", "through"): TravelProfile("local-fast-stop-through", 0.14, 0.04, 38),
    ("local_fast", "through", "to_stop"): TravelProfile("local-fast-through-stop", 0.04, 0.14, 38),
    ("local_fast", "through", "through"): TravelProfile("local-fast-through-through", 0.03, 0.03, 32),
    ("puyuma", "from_stop", "to_stop"): TravelProfile("puyuma-stop-stop", 0.10, 0.10, 36),
    ("puyuma", "from_stop", "through"): TravelProfile("puyuma-stop-through", 0.09, 0.03, 32),
    ("puyuma", "through", "to_stop"): TravelProfile("puyuma-through-stop", 0.03, 0.09, 32),
    ("puyuma", "through", "through"): TravelProfile("puyuma-through-through", 0.02, 0.02, 28),
    ("express_3000", "from_stop", "to_stop"): TravelProfile("express3000-stop-stop", 0.10, 0.10, 35),
    ("express_3000", "from_stop", "through"): TravelProfile("express3000-stop-through", 0.08, 0.03, 30),
    ("express_3000", "through", "to_stop"): TravelProfile("express3000-through-stop", 0.03, 0.08, 30),
    ("express_3000", "through", "through"): TravelProfile("express3000-through-through", 0.02, 0.02, 26),
    ("express", "from_stop", "to_stop"): TravelProfile("express-stop-stop", 0.11, 0.11, 38),
    ("express", "from_stop", "through"): TravelProfile("express-stop-through", 0.09, 0.03, 32),
    ("express", "through", "to_stop"): TravelProfile("express-through-stop", 0.03, 0.09, 32),
    ("express", "through", "through"): TravelProfile("express-through-through", 0.02, 0.02, 28),
    ("default", "from_stop", "to_stop"): TravelProfile("default-stop-stop", 0.12, 0.12, 45),
    ("default", "from_stop", "through"): TravelProfile("default-stop-through", 0.10, 0.04, 38),
    ("default", "through", "to_stop"): TravelProfile("default-through-stop", 0.04, 0.10, 38),
    ("default", "through", "through"): TravelProfile("default-through-through", 0.03, 0.03, 34),
}


class TravelProfileService:
    def classify_train_type_family(self, train_type_name: str | None) -> str:
        normalized = (train_type_name or "").strip().lower()
        if "普悠瑪" in (train_type_name or "") or "puyuma" in normalized:
            return "puyuma"
        if "3000" in (train_type_name or ""):
            return "express_3000"
        if "區間快" in (train_type_name or ""):
            return "local_fast"
        if "區間" in (train_type_name or ""):
            return "local"
        if "自強" in (train_type_name or "") or "莒光" in (train_type_name or "") or "太魯閣" in (train_type_name or ""):
            return "express"
        return "default"

    def estimate(
        self,
        *,
        ratio: float,
        train_type_name: str | None,
        upstream_dwell_seconds: int,
        downstream_dwell_seconds: int,
    ) -> TravelProfileEstimate:
        ratio = min(max(ratio, 0.0), 1.0)
        family = self.classify_train_type_family(train_type_name)
        start_state = "from_stop" if upstream_dwell_seconds > 0 else "through"
        end_state = "to_stop" if downstream_dwell_seconds > 0 else "through"
        profile = PROFILE_DEFAULTS.get((family, start_state, end_state)) or PROFILE_DEFAULTS[("default", start_state, end_state)]
        return TravelProfileEstimate(
            profile_id=profile.profile_id,
            train_type_family=family,
            time_fraction=self._time_fraction_for_ratio(ratio, profile),
            base_uncertainty_seconds=profile.base_uncertainty_seconds,
        )

    def _time_fraction_for_ratio(self, ratio: float, profile: TravelProfile) -> float:
        ratio = min(max(ratio, 0.0), 1.0)
        accel_time = min(max(profile.accel_time_fraction, 0.0), 0.45)
        decel_time = min(max(profile.decel_time_fraction, 0.0), 0.45)
        cruise_time = max(1.0 - accel_time - decel_time, 0.01)
        peak_speed = 1.0 / (cruise_time + 0.5 * accel_time + 0.5 * decel_time)
        accel_distance = 0.5 * accel_time * peak_speed
        cruise_distance = cruise_time * peak_speed
        decel_distance = 0.5 * decel_time * peak_speed

        if ratio <= accel_distance and accel_time > 0:
            return min(max(((2.0 * accel_time * ratio) / peak_speed) ** 0.5, 0.0), 1.0)

        if ratio <= accel_distance + cruise_distance:
            cruise_progress = ratio - accel_distance
            return min(max(accel_time + (cruise_progress / peak_speed), 0.0), 1.0)

        if decel_time <= 0 or decel_distance <= 0:
            return 1.0

        remaining_distance = max(1.0 - ratio, 0.0)
        remaining_time = ((2.0 * decel_time * remaining_distance) / peak_speed) ** 0.5
        return min(max(1.0 - remaining_time, 0.0), 1.0)