from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.services.mobile_bundle_audit import build_mobile_bundle_accuracy_audit


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    default_bundle = ROOT_DIR.parent / "PhoneApp" / "assets" / "data" / "crossradar_mobile_bundle.json"
    default_output = ROOT_DIR / ".runtime" / "prediction" / "mobile_bundle_accuracy_audit.json"

    parser = argparse.ArgumentParser(description="Audit mobile bundle coverage against embedded calibration observations.")
    parser.add_argument("--bundle", type=Path, default=default_bundle, help="Path to the mobile bundle JSON.")
    parser.add_argument("--output", type=Path, default=default_output, help="Where to write the audit JSON report.")
    parser.add_argument(
        "--observation-replay",
        type=Path,
        help="Optional replay artifact whose observations should override the bundle-embedded calibration observations during the audit.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if the audit still finds missing runtime pairs, missing or unusable projections, or liveboard evidence gaps.",
    )
    args = parser.parse_args()

    bundle = _read_json(args.bundle)
    observations_override = None
    if args.observation_replay is not None:
        replay_payload = _read_json(args.observation_replay)
        observations_override = replay_payload.get("observations") or []
    report = build_mobile_bundle_accuracy_audit(bundle, observations_override=observations_override)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"wrote {args.output}")
    print(
        "mobile_bundle_accuracy_audit "
        f"observations={summary['ok_observation_count']} "
        f"missing_pairs={summary['missing_runtime_pair_count']} "
        f"missing_projections={summary['missing_station_projection_count']} "
        f"unusable_projections={summary['unusable_station_projection_count']} "
        f"liveboard_gaps={summary['runtime_not_using_liveboard_evidence_count']}"
    )
    if args.strict and (
        summary["missing_runtime_pair_count"]
        or summary["missing_station_projection_count"]
        or summary["unusable_station_projection_count"]
        or summary["runtime_not_using_liveboard_evidence_count"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
