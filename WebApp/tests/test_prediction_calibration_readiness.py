from scripts.build_prediction_calibration import build_calibration_readiness


def _row(
    row_id: str,
    error_seconds: int,
    *,
    crossing_id: str = "cr-1",
    direction: int = 0,
    upstream_station_id: str = "A",
    train_type_family: str = "local",
    calibration_eligible: bool = True,
) -> dict[str, object]:
    return {
        "id": row_id,
        "status": "ok",
        "crossing_id": crossing_id,
        "direction": direction,
        "upstream_station_id": upstream_station_id,
        "train_type_family": train_type_family,
        "rule_error_seconds": error_seconds,
        "calibration_eligible": calibration_eligible,
    }


def test_build_calibration_readiness_reports_ready_family_group() -> None:
    readiness = build_calibration_readiness([
        _row("obs-1", -12),
        _row("obs-2", -8),
    ])

    assert readiness["eligible_observation_count"] == 2
    assert readiness["family_ready_count"] == 1
    assert readiness["segment_ready_count"] == 0
    assert readiness["family_groups"][0]["reason"] == "ready"
    assert readiness["family_groups"][0]["offset_seconds"] == 10
    assert readiness["segment_groups"][0]["reason"] == "insufficient_samples"


def test_build_calibration_readiness_reports_wide_spread_group() -> None:
    readiness = build_calibration_readiness([
        _row("obs-1", 0),
        _row("obs-2", 15),
        _row("obs-3", 35),
    ])

    assert readiness["family_ready_count"] == 0
    assert readiness["segment_ready_count"] == 0
    assert readiness["family_groups"][0]["reason"] == "spread_too_wide"
    assert readiness["segment_groups"][0]["reason"] == "spread_too_wide"