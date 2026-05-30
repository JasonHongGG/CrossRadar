from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any


def _ratio_key(upstream_station_id: str, downstream_station_id: str) -> str:
    return f"{upstream_station_id}|{downstream_station_id}"


def _projection_key(station_id: str, upstream_station_id: str, downstream_station_id: str) -> str:
    return f"{station_id}|{upstream_station_id}|{downstream_station_id}"


def build_mobile_bundle_accuracy_audit(bundle: dict[str, Any], *, observations_override: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    calibration = bundle.get("calibration") or {}
    observations = observations_override if observations_override is not None else (calibration.get("observations") or [])
    crossings = bundle.get("crossings") or []
    crossing_by_id = {
        str(crossing.get("id") or "").strip(): crossing
        for crossing in crossings
        if str(crossing.get("id") or "").strip()
    }
    station_pair_projections = bundle.get("station_pair_projections") or {}
    station_pair_projection_rejections = bundle.get("station_pair_projection_rejections") or {}

    rows: list[dict[str, Any]] = []
    missing_pairs: Counter[str] = Counter()
    missing_projections: Counter[str] = Counter()
    unusable_projections: Counter[str] = Counter()
    gap_types: Counter[str] = Counter()
    missing_pair_crossings: Counter[str] = Counter()
    missing_projection_crossings: Counter[str] = Counter()
    unusable_projection_crossings: Counter[str] = Counter()

    ok_rows = [row for row in observations if row.get("status") == "ok"]
    liveboard_benchmark_rows = [row for row in ok_rows if row.get("benchmark_delay_source") == "liveboard"]

    for observation in ok_rows:
        crossing_id = str(observation.get("crossing_id") or "").strip()
        crossing = crossing_by_id.get(crossing_id) or {}
        runtime_ratios = crossing.get("runtime_ratios") or {}
        runtime_ratio_rejections = crossing.get("runtime_ratio_rejections") or {}

        upstream_station_id = str(observation.get("upstream_station_id") or "").strip()
        downstream_station_id = str(observation.get("downstream_station_id") or "").strip()
        liveboard_station_id = str(observation.get("tdx_liveboard_station_id") or "").strip()

        pair_key = _ratio_key(upstream_station_id, downstream_station_id)
        pair_present = pair_key in runtime_ratios
        pair_rejection = runtime_ratio_rejections.get(pair_key)

        liveboard_evidence_expected = observation.get("benchmark_delay_source") == "liveboard"
        projection_required = bool(
            liveboard_station_id
            and liveboard_evidence_expected
            and liveboard_station_id not in {upstream_station_id, downstream_station_id}
        )
        projection_key = (
            _projection_key(liveboard_station_id, upstream_station_id, downstream_station_id)
            if projection_required
            else None
        )
        projection_present = projection_key in station_pair_projections if projection_key is not None else None
        projection_rejection = station_pair_projection_rejections.get(projection_key or "") if projection_key is not None else None

        observation_gap_types: list[str] = []
        if not pair_present:
            observation_gap_types.append("missing_runtime_pair")
            missing_pairs[pair_key] += 1
            missing_pair_crossings[crossing_id] += 1
        if projection_required and not projection_present:
            if projection_rejection is None:
                observation_gap_types.append("missing_station_projection")
                if projection_key is not None:
                    missing_projections[projection_key] += 1
                missing_projection_crossings[crossing_id] += 1
            else:
                observation_gap_types.append("unusable_station_projection")
                if projection_key is not None:
                    unusable_projections[projection_key] += 1
                unusable_projection_crossings[crossing_id] += 1
        if liveboard_evidence_expected and observation.get("runtime_delay_source") != "liveboard":
            observation_gap_types.append("runtime_not_using_liveboard_evidence")

        for gap_type in observation_gap_types:
            gap_types[gap_type] += 1

        rows.append(
            {
                "id": observation.get("id"),
                "crossing_id": crossing_id,
                "train_no": observation.get("train_no"),
                "direction": observation.get("direction"),
                "upstream_station_id": upstream_station_id,
                "downstream_station_id": downstream_station_id,
                "tdx_liveboard_station_id": liveboard_station_id or None,
                "pair_key": pair_key,
                "pair_present": pair_present,
                "pair_rejection": pair_rejection,
                "projection_required": projection_required,
                "projection_key": projection_key,
                "projection_present": projection_present,
                "projection_rejection": projection_rejection,
                "runtime_delay_source": observation.get("runtime_delay_source"),
                "runtime_delay_reason": observation.get("runtime_delay_reason"),
                "runtime_liveboard_context_present": observation.get("runtime_liveboard_context_present"),
                "runtime_liveboard_fallback_reason": observation.get("runtime_liveboard_fallback_reason"),
                "runtime_projection_reason": observation.get("runtime_projection_reason"),
                "runtime_selected_liveboard_station_id": observation.get("runtime_selected_liveboard_station_id"),
                "benchmark_delay_source": observation.get("benchmark_delay_source"),
                "runtime_error_seconds": observation.get("runtime_error_seconds"),
                "benchmark_error_seconds": observation.get("benchmark_error_seconds"),
                "gap_types": observation_gap_types,
            }
        )

    summary = {
        "observation_count": len(observations),
        "ok_observation_count": len(ok_rows),
        "bundle_crossing_count": len(crossings),
        "bundle_runtime_ratio_count": int((bundle.get("metadata") or {}).get("runtime_ratio_count") or 0),
        "bundle_station_pair_projection_count": int((bundle.get("metadata") or {}).get("station_pair_projection_count") or 0),
        "bundle_station_pair_projection_rejection_count": int((bundle.get("metadata") or {}).get("station_pair_projection_rejection_count") or 0),
        "liveboard_benchmark_case_count": len(liveboard_benchmark_rows),
        "pair_coverage_count": sum(1 for row in rows if row["pair_present"]),
        "missing_runtime_pair_count": gap_types["missing_runtime_pair"],
        "projection_required_count": sum(1 for row in rows if row["projection_required"]),
        "projection_coverage_count": sum(1 for row in rows if row["projection_required"] and row["projection_present"]),
        "missing_station_projection_count": gap_types["missing_station_projection"],
        "unusable_station_projection_count": gap_types["unusable_station_projection"],
        "runtime_not_using_liveboard_evidence_count": gap_types["runtime_not_using_liveboard_evidence"],
        "observations_with_any_gap_count": sum(1 for row in rows if row["gap_types"]),
    }

    generated_at = datetime.now(UTC).isoformat()
    return {
        "metadata": {
            "generated_at": generated_at,
            "bundle_generated_at": (bundle.get("metadata") or {}).get("generated_at"),
            "bundle_schema_version": (bundle.get("metadata") or {}).get("schema_version"),
            "observation_source": (calibration.get("metadata") or {}).get("generated_from"),
        },
        "summary": summary,
        "top_missing_runtime_pairs": [
            {"pair_key": pair_key, "count": count}
            for pair_key, count in missing_pairs.most_common(20)
        ],
        "top_missing_station_projections": [
            {"projection_key": projection_key, "count": count}
            for projection_key, count in missing_projections.most_common(20)
        ],
        "top_unusable_station_projections": [
            {"projection_key": projection_key, "count": count}
            for projection_key, count in unusable_projections.most_common(20)
        ],
        "missing_runtime_pair_crossings": [
            {"crossing_id": crossing_id, "count": count}
            for crossing_id, count in missing_pair_crossings.most_common(20)
        ],
        "missing_station_projection_crossings": [
            {"crossing_id": crossing_id, "count": count}
            for crossing_id, count in missing_projection_crossings.most_common(20)
        ],
        "unusable_station_projection_crossings": [
            {"crossing_id": crossing_id, "count": count}
            for crossing_id, count in unusable_projection_crossings.most_common(20)
        ],
        "observations": rows,
    }
