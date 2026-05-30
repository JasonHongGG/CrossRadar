from __future__ import annotations

from backend.app.services.mobile_bundle_audit import build_mobile_bundle_accuracy_audit


def test_audit_flags_missing_pair_and_projection() -> None:
    bundle = {
        "metadata": {
            "schema_version": 2,
            "generated_at": "2026-05-30T00:00:00+00:00",
            "runtime_ratio_count": 1,
            "station_pair_projection_count": 0,
        },
        "crossings": [
            {
                "id": "crossing-1",
                "runtime_ratios": {
                    "A|B": {
                        "upstream_station_id": "A",
                        "downstream_station_id": "B",
                        "ratio": 0.5,
                        "source": "osm_path",
                    }
                },
                "runtime_ratio_rejections": {
                    "B|C": {
                        "source": "unavailable",
                        "note": "missing pair",
                    }
                },
            }
        ],
        "station_pair_projections": {},
        "station_pair_projection_rejections": {},
        "calibration": {
            "metadata": {"generated_from": "test-observations"},
            "observations": [
                {
                    "id": "obs-1",
                    "status": "ok",
                    "crossing_id": "crossing-1",
                    "train_no": "3001",
                    "direction": 0,
                    "upstream_station_id": "B",
                    "downstream_station_id": "C",
                    "tdx_liveboard_station_id": "X",
                    "runtime_delay_source": "none",
                    "benchmark_delay_source": "liveboard",
                    "runtime_error_seconds": 60,
                    "benchmark_error_seconds": 15,
                }
            ],
        },
    }

    report = build_mobile_bundle_accuracy_audit(bundle)

    assert report["summary"]["missing_runtime_pair_count"] == 1
    assert report["summary"]["missing_station_projection_count"] == 1
    assert report["summary"]["runtime_not_using_liveboard_evidence_count"] == 1
    assert report["observations"][0]["gap_types"] == [
        "missing_runtime_pair",
        "missing_station_projection",
        "runtime_not_using_liveboard_evidence",
    ]


def test_audit_recognizes_complete_observation_coverage() -> None:
    bundle = {
        "metadata": {
            "schema_version": 2,
            "generated_at": "2026-05-30T00:00:00+00:00",
            "runtime_ratio_count": 2,
            "station_pair_projection_count": 1,
        },
        "crossings": [
            {
                "id": "crossing-1",
                "runtime_ratios": {
                    "B|C": {
                        "upstream_station_id": "B",
                        "downstream_station_id": "C",
                        "ratio": 0.35,
                        "source": "osm_path",
                    }
                },
                "runtime_ratio_rejections": {},
            }
        ],
        "station_pair_projections": {
            "X|B|C": {
                "station_id": "X",
                "upstream_station_id": "B",
                "downstream_station_id": "C",
                "ratio": 0.25,
                "source": "osm_path",
            }
        },
        "station_pair_projection_rejections": {},
        "calibration": {
            "metadata": {"generated_from": "test-observations"},
            "observations": [
                {
                    "id": "obs-1",
                    "status": "ok",
                    "crossing_id": "crossing-1",
                    "train_no": "3001",
                    "direction": 0,
                    "upstream_station_id": "B",
                    "downstream_station_id": "C",
                    "tdx_liveboard_station_id": "X",
                    "runtime_delay_source": "liveboard",
                    "benchmark_delay_source": "liveboard",
                    "runtime_error_seconds": 15,
                    "benchmark_error_seconds": 15,
                }
            ],
        },
    }

    report = build_mobile_bundle_accuracy_audit(bundle)

    assert report["summary"]["missing_runtime_pair_count"] == 0
    assert report["summary"]["missing_station_projection_count"] == 0
    assert report["summary"]["unusable_station_projection_count"] == 0
    assert report["summary"]["runtime_not_using_liveboard_evidence_count"] == 0
    assert report["observations"][0]["gap_types"] == []


def test_audit_distinguishes_unusable_projection_rejection() -> None:
    bundle = {
        "metadata": {
            "schema_version": 2,
            "generated_at": "2026-05-30T00:00:00+00:00",
            "runtime_ratio_count": 1,
            "station_pair_projection_count": 0,
            "station_pair_projection_rejection_count": 1,
        },
        "crossings": [
            {
                "id": "crossing-1",
                "runtime_ratios": {
                    "B|C": {
                        "upstream_station_id": "B",
                        "downstream_station_id": "C",
                        "ratio": 0.35,
                        "source": "osm_path",
                    }
                },
                "runtime_ratio_rejections": {},
            }
        ],
        "station_pair_projections": {},
        "station_pair_projection_rejections": {
            "X|B|C": {
                "station_id": "X",
                "upstream_station_id": "B",
                "downstream_station_id": "C",
                "source": "unavailable",
                "confidence": "low",
                "note": "Rejected the stop-pair OSM ratio.",
            }
        },
        "calibration": {
            "metadata": {"generated_from": "test-observations"},
            "observations": [
                {
                    "id": "obs-1",
                    "status": "ok",
                    "crossing_id": "crossing-1",
                    "train_no": "3001",
                    "direction": 0,
                    "upstream_station_id": "B",
                    "downstream_station_id": "C",
                    "tdx_liveboard_station_id": "X",
                    "runtime_delay_source": "liveboard",
                    "benchmark_delay_source": "liveboard",
                    "runtime_error_seconds": 15,
                    "benchmark_error_seconds": 15,
                }
            ],
        },
    }

    report = build_mobile_bundle_accuracy_audit(bundle)

    assert report["summary"]["missing_station_projection_count"] == 0
    assert report["summary"]["unusable_station_projection_count"] == 1
    assert report["observations"][0]["gap_types"] == ["unusable_station_projection"]