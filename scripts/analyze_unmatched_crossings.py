from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.dependencies import get_crossing_catalog_service


REPORT_PATH = Path("data/crossings/unmatched_crossings_analysis.json")


def _runtime_reason_detail(
    explicit_exclusion: dict[str, Any] | None,
    *,
    has_geometry: bool,
) -> tuple[str, str, bool, str | None]:
    if explicit_exclusion is not None:
        note = explicit_exclusion.get("note")
        detail = explicit_exclusion.get("reason") or "Explicitly excluded from the runtime curated dataset."
        return (
            "explicit_runtime_exclusion",
            detail,
            False,
            note,
        )

    if has_geometry:
        return (
            "excluded_from_runtime_for_other_reason",
            "This crossing is not present in crossings_curated.geojson even though geometry exists; inspect runtime selection rules and exclusion metadata.",
            True,
            None,
        )

    return (
        "no_adopted_geometry",
        "This crossing is currently excluded from crossings_curated.geojson because no adopted runtime geometry is available.",
        True,
        None,
    )


async def main() -> None:
    catalog = get_crossing_catalog_service()
    full_dataset = await catalog.load_full()
    curated_dataset = await catalog.load()
    exclusion_lookup = catalog._load_runtime_exclusion_lookup()
    curated_ids = {
        str(feature.get("properties", {}).get("crossing_id") or feature.get("id"))
        for feature in curated_dataset.get("features", [])
    }

    entries: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    reviewable_count = 0
    explicit_runtime_exclusion_count = 0

    for feature in full_dataset.get("features", []):
        properties = feature.get("properties", {})
        crossing_id = str(properties.get("crossing_id") or feature.get("id") or "")
        if not crossing_id or crossing_id in curated_ids:
            continue
        explicit_exclusion = exclusion_lookup.get(crossing_id)
        reason_code, reason_detail, reviewable, exclusion_note = _runtime_reason_detail(
            explicit_exclusion,
            has_geometry=feature.get("geometry") is not None,
        )
        reason_counts[reason_code] += 1
        if reviewable:
            reviewable_count += 1
        if explicit_exclusion is not None:
            explicit_runtime_exclusion_count += 1

        entries.append(
            {
                "crossing_id": crossing_id,
                "name": properties.get("name"),
                "normalized_name": properties.get("normalized_name"),
                "line": properties.get("line"),
                "km_marker": properties.get("km_marker"),
                "km_value_meters": properties.get("km_value_meters"),
                "road_type": properties.get("road_type"),
                "query_station_pair_text": properties.get("query_station_pair_text"),
                "query_station_a_name": properties.get("query_station_a_name"),
                "query_station_b_name": properties.get("query_station_b_name"),
                "station_pair_text": properties.get("station_pair_text"),
                "station_a_name": properties.get("station_a_name"),
                "station_b_name": properties.get("station_b_name"),
                "county": properties.get("county"),
                "current_match": {
                    "score": properties.get("match_score"),
                    "method": properties.get("match_method"),
                    "confidence": properties.get("geolocation_confidence"),
                    "matched_osm_id": properties.get("matched_osm_id"),
                },
                "analysis": {
                    "reason_code": reason_code,
                    "reason_detail": reason_detail,
                    "reviewable": reviewable,
                    "has_geometry": feature.get("geometry") is not None,
                    "explicit_runtime_exclusion": explicit_exclusion is not None,
                    "exclusion_note": exclusion_note,
                    "recommended_next_step": (
                        None
                        if not reviewable
                        else "Manual review or an explicit geometry override is still required before this crossing can return to crossings_curated.geojson."
                    ),
                },
                "name_match_candidates": [],
            }
        )

    report = {
        "metadata": {
            "full_count": len(full_dataset.get("features", [])),
            "curated_count": len(curated_dataset.get("features", [])),
            "official_count": len(full_dataset.get("features", [])),
            "mapped_count": len(curated_dataset.get("features", [])),
            "unmatched_count": len(entries),
            "excluded_count": len(entries),
            "reviewable_count": reviewable_count,
            "explicit_runtime_exclusion_count": explicit_runtime_exclusion_count,
            "osm_feature_count": full_dataset.get("metadata", {}).get("osm_feature_count", 0),
            "report_path": str(REPORT_PATH),
            "report_scope": "crossings_full.geojson minus crossings_curated.geojson",
        },
        "summary": {
            "reason_counts": dict(reason_counts),
            "matcher_observation": "This report now tracks only crossings that are absent from the runtime curated dataset.",
            "km_fallback_observation": "Resolved and manually patched crossings are intentionally omitted once they are back in crossings_curated.geojson.",
        },
        "entries": entries,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["metadata"], ensure_ascii=False, indent=2))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())