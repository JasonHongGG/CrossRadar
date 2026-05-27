from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.dependencies import get_crossing_catalog_service, get_crossing_scraper, get_osm_enricher
from backend.app.models.crossing import CrossingRecord
from backend.app.utils import normalize_text


REPORT_PATH = Path("data/crossings/unmatched_crossings_analysis.json")
ROAD_NAME_SUFFIXES = ("路", "街", "巷", "大道", "道", "橋")
FACILITY_SUFFIXES = ("公司", "礦場", "農場", "碼頭")


def _line_matches(official_line: str, rail_names: list[str]) -> bool:
    normalized_line = normalize_text(official_line)
    if not normalized_line:
        return False
    for rail_name in rail_names:
        normalized_rail_name = normalize_text(rail_name)
        if normalized_rail_name and (
            normalized_line in normalized_rail_name or normalized_rail_name in normalized_line
        ):
            return True
    return False


def _name_match_candidates(
    catalog: Any,
    record: CrossingRecord,
    osm_features: list[dict[str, Any]],
    *,
    station_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for feature in osm_features:
        score, method = catalog._score_match(record, feature, station_context=station_context)
        if score <= 0:
            continue
        properties = feature.get("properties", {})
        candidates.append(
            {
                "osm_id": properties.get("osm_id"),
                "score": score,
                "method": method,
                "name": properties.get("name"),
                "road_names": properties.get("road_names", []),
                "rail_names": properties.get("rail_names", []),
                "railway_position": properties.get("railway_position"),
                "railway_position_meters": properties.get("railway_position_meters"),
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def _same_line_candidates(record: CrossingRecord, osm_features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for feature in osm_features:
        properties = feature.get("properties", {})
        rail_names = properties.get("rail_names", [])
        if _line_matches(record.line, rail_names):
            candidates.append(feature)
    return candidates


def _manual_mapping_category(record: CrossingRecord, duplicate_normalized_name: bool) -> str:
    if duplicate_normalized_name:
        return "duplicate_official_name_requires_km_disambiguation"
    if record.name.endswith(FACILITY_SUFFIXES) or record.road_type == "專用":
        return "facility_or_private_crossing_name_not_reflected_in_osm"
    if record.name.endswith(ROAD_NAME_SUFFIXES):
        return "road_name_mismatch_or_unnamed_osm_road"
    return "local_place_name_not_reflected_in_osm"


def _reason_detail(
    name_candidates: list[dict[str, Any]],
    same_line_candidates: list[dict[str, Any]],
    same_line_with_position: list[dict[str, Any]],
) -> tuple[str, str]:
    if not name_candidates:
        detail = "Official crossing name does not overlap any OSM node name, road name, or rail name candidate."
        if same_line_candidates and not same_line_with_position:
            detail += " OSM has same-line crossings, but none of them expose railway:position, so the current matcher cannot fall back to kilometer-based disambiguation."
        return ("no_name_overlap", detail)
    top_candidate = name_candidates[0]
    if top_candidate["score"] < 45:
        return (
            "name_overlap_below_threshold",
            "A weak name overlap exists, but the top candidate score stays below the current acceptance threshold of 45.",
        )
    return (
        "review_needed",
        "A candidate exists but it was still rejected by the current matcher and should be reviewed manually.",
    )


def _recommended_next_step(category: str, same_line_with_position_count: int) -> str:
    if category == "duplicate_official_name_requires_km_disambiguation":
        return "Use station-pair context plus manual OSM review; if OSM later gains railway:position tags, kilometer-based disambiguation becomes possible."
    if category == "facility_or_private_crossing_name_not_reflected_in_osm":
        return "Check nearby unnamed or service-road OSM crossings and add an alias or manual mapping table for private crossings."
    if same_line_with_position_count == 0:
        return "Manual visual mapping is required first because name matching failed and same-line OSM crossings do not provide railway:position tags."
    return "Review same-line OSM candidates and extend the matcher with an alias or kilometer fallback."


async def main() -> None:
    catalog = get_crossing_catalog_service()
    scraper = get_crossing_scraper()
    osm_enricher = get_osm_enricher()

    official_records = scraper.load_cached()
    route_referenced_records = [catalog.route_reference_service.apply(record.model_copy(deep=True)) for record in official_records]
    station_context_lookup = await catalog._build_station_context_lookup(route_referenced_records)
    osm_geojson = await osm_enricher.build_geojson(force_refresh=False)
    osm_features = osm_geojson.get("features", [])

    normalized_name_counts = Counter((record.line.strip(), record.normalized_name) for record in route_referenced_records)

    entries: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    duplicate_groups: list[dict[str, Any]] = []

    seen_duplicate_groups: set[tuple[str, str]] = set()

    for record in route_referenced_records:
        station_context = station_context_lookup.get(record.crossing_id)
        matched_feature, score, method, confidence = catalog._match_official_to_osm(
            record,
            osm_features,
            station_context=station_context,
        )
        if matched_feature is not None and confidence in ("high", "medium"):
            continue

        duplicate_key = (record.line.strip(), record.normalized_name)
        duplicate_normalized_name = normalized_name_counts[duplicate_key] > 1
        if duplicate_normalized_name and duplicate_key not in seen_duplicate_groups:
            seen_duplicate_groups.add(duplicate_key)
            duplicate_groups.append(
                {
                    "line": duplicate_key[0],
                    "normalized_name": duplicate_key[1],
                    "count": normalized_name_counts[duplicate_key],
                }
            )

        name_candidates = _name_match_candidates(catalog, record, osm_features, station_context=station_context)
        same_line_candidates = _same_line_candidates(record, osm_features)
        same_line_with_position = [
            feature for feature in same_line_candidates if feature.get("properties", {}).get("railway_position_meters") is not None
        ]

        reason_code, reason_detail = _reason_detail(name_candidates, same_line_candidates, same_line_with_position)
        category = _manual_mapping_category(record, duplicate_normalized_name)
        recommended_next_step = _recommended_next_step(category, len(same_line_with_position))

        reason_counts[reason_code] += 1
        category_counts[category] += 1

        entries.append(
            {
                "crossing_id": record.crossing_id,
                "name": record.name,
                "normalized_name": record.normalized_name,
                "line": record.line,
                "km_marker": record.km_marker,
                "km_value_meters": record.km_value_meters,
                "road_type": record.road_type,
                "station_pair_text": record.station_pair_text,
                "station_a_name": record.station_a_name,
                "station_b_name": record.station_b_name,
                "county": record.county,
                "current_match": {
                    "score": score,
                    "method": method,
                    "confidence": confidence,
                    "matched_osm_id": matched_feature.get("properties", {}).get("osm_id") if matched_feature else None,
                },
                "analysis": {
                    "reason_code": reason_code,
                    "reason_detail": reason_detail,
                    "manual_mapping_category": category,
                    "duplicate_normalized_name_on_same_line": duplicate_normalized_name,
                    "same_line_osm_feature_count": len(same_line_candidates),
                    "same_line_with_railway_position_count": len(same_line_with_position),
                    "recommended_next_step": recommended_next_step,
                },
                "name_match_candidates": name_candidates[:5],
            }
        )

    report = {
        "metadata": {
            "official_count": len(official_records),
            "mapped_count": len(official_records) - len(entries),
            "unmatched_count": len(entries),
            "osm_feature_count": len(osm_features),
            "report_path": str(REPORT_PATH),
        },
        "summary": {
            "reason_counts": dict(reason_counts),
            "manual_mapping_category_counts": dict(category_counts),
            "normalized_duplicate_groups": duplicate_groups,
            "matcher_observation": "All currently unmatched official crossings fail before thresholding because the current matcher cannot find any overlapping OSM name candidate.",
            "km_fallback_observation": "Same-line OSM candidates exist, but for these unmatched records none of those same-line OSM crossings expose railway:position, so the current matcher has no kilometer-based fallback.",
        },
        "entries": entries,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["metadata"], ensure_ascii=False, indent=2))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())