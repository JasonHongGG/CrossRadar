from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.build_prediction_calibration import build_calibration_readiness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit mobile bundle calibration readiness from embedded observation rows.")
    parser.add_argument("--bundle", type=Path, default=ROOT_DIR.parent / "PhoneApp" / "assets" / "data" / "crossradar_mobile_bundle.json")
    parser.add_argument("--output", type=Path, default=ROOT_DIR / ".runtime" / "prediction" / "mobile_bundle_calibration_readiness.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    calibration = bundle.get("calibration") or {}
    readiness = build_calibration_readiness(calibration.get("observations") or [])
    payload: dict[str, Any] = {
        "bundle_path": str(args.bundle),
        "calibration_metadata": calibration.get("metadata") or {},
        "rules_count": len(calibration.get("rules") or []),
        "readiness": readiness,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")
    print(
        json.dumps(
            {
                "rules_count": payload["rules_count"],
                "eligible_observation_count": readiness["eligible_observation_count"],
                "family_ready_count": readiness["family_ready_count"],
                "segment_ready_count": readiness["segment_ready_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()