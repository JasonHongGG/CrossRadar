from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from backend.app.dependencies import get_predictor_service, get_settings, get_station_graph_service, get_tdx_client
from backend.app.utils import project_point_onto_station_line

MAX_STATION_PROJECTION_OFFSET_METERS = 1500.0
MAX_STATION_PROJECTIONS_PER_PAIR = 3
MAX_TIMETABLE_RUNTIME_PAIRS_PER_CROSSING = 8


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _compact_position(position: dict[str, Any] | None) -> dict[str, float] | None:
    position = position or {}
    lat = position.get("PositionLat")
    lon = position.get("PositionLon")
    if lat is None or lon is None:
        return None
    return {"lat": float(lat), "lon": float(lon)}


def _feature_geometry(feature: dict[str, Any]) -> dict[str, float] | None:
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2 or coordinates[0] is None or coordinates[1] is None:
        return None
    return {"lon": float(coordinates[0]), "lat": float(coordinates[1])}


def _ratio_key(upstream_station_id: str, downstream_station_id: str) -> str:
    return f"{upstream_station_id}|{downstream_station_id}"


def _add_ratio(
    ratios: dict[str, dict[str, Any]],
    *,
    upstream_station_id: str | None,
    downstream_station_id: str | None,
    ratio: float | None,
    source: str | None,
    confidence: str | None,
    note: str | None,
) -> None:
    if not upstream_station_id or not downstream_station_id or ratio is None:
        return
    if source != "osm_path":
        return
    ratio = max(0.0, min(1.0, float(ratio)))
    ratios[_ratio_key(str(upstream_station_id), str(downstream_station_id))] = {
        "upstream_station_id": str(upstream_station_id),
        "downstream_station_id": str(downstream_station_id),
        "ratio": ratio,
        "source": "osm_path",
        "confidence": confidence or "high",
        "note": note,
    }


def _add_rejection(
    rejections: dict[str, dict[str, Any]],
    *,
    upstream_station_id: str | None,
    downstream_station_id: str | None,
    source: str | None,
    confidence: str | None,
    note: str | None,
) -> None:
    if not upstream_station_id or not downstream_station_id:
        return
    key = _ratio_key(str(upstream_station_id), str(downstream_station_id))
    rejections.setdefault(
        key,
        {
            "upstream_station_id": str(upstream_station_id),
            "downstream_station_id": str(downstream_station_id),
            "source": source or "unavailable",
            "confidence": confidence or "low",
            "note": note,
        },
    )


def _station_name(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    station_name = value.get("StationName") or {}
    return station_name.get("Zh_tw") or station_name.get("En")


def _station_position(station: dict[str, Any] | None) -> dict[str, float] | None:
    position = (station or {}).get("StationPosition") or (station or {}).get("position") or {}
    lat = position.get("PositionLat") if isinstance(position, dict) else None
    lon = position.get("PositionLon") if isinstance(position, dict) else None
    if lat is None and isinstance(position, dict):
        lat = position.get("lat")
    if lon is None and isinstance(position, dict):
        lon = position.get("lon")
    if lat is None or lon is None:
        return None
    return {"PositionLat": float(lat), "PositionLon": float(lon)}


def _candidate_station_projection_ids(
    *,
    upstream_station_id: str,
    downstream_station_id: str,
    station_lookup_by_id: dict[str, dict[str, Any]],
    max_offset_meters: float = MAX_STATION_PROJECTION_OFFSET_METERS,
    max_candidates: int = MAX_STATION_PROJECTIONS_PER_PAIR,
) -> list[str]:
    upstream = _station_position(station_lookup_by_id.get(upstream_station_id))
    downstream = _station_position(station_lookup_by_id.get(downstream_station_id))
    if upstream is None or downstream is None:
        return []

    station_ids: list[tuple[float, str]] = []
    for station_id, station in station_lookup_by_id.items():
        if station_id in {upstream_station_id, downstream_station_id}:
            continue
        position = _station_position(station)
        if position is None:
            continue
        projection = project_point_onto_station_line(
            upstream["PositionLon"],
            upstream["PositionLat"],
            downstream["PositionLon"],
            downstream["PositionLat"],
            position["PositionLon"],
            position["PositionLat"],
        )
        if 0.0 < projection["ratio"] < 1.0 and projection["offset_meters"] <= max_offset_meters:
            station_ids.append((float(projection["offset_meters"]), str(station_id)))
    station_ids.sort(key=lambda item: item[0])
    return [station_id for _, station_id in station_ids[:max_candidates]]


async def _load_timetable_snapshot(*, enabled: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not enabled:
        return [], {"available": False, "skipped": True}
    try:
        result = await get_tdx_client().get_today_timetables_snapshot(force_refresh=False)
    except Exception as exc:  # noqa: BLE001 - exporter should still produce an anchor-only bundle if TDX is unavailable.
        return [], {"available": False, "error": type(exc).__name__}
    return result.value, {
        "available": True,
        "fetched_from": result.fetched_from,
        "cached_at": result.cached_at.isoformat() if result.cached_at else None,
        "record_count": len(result.value),
    }


async def export_mobile_bundle(output_path: Path, *, use_timetable_snapshot: bool = True) -> dict[str, Any]:
    print("export_mobile_bundle_stage init", flush=True)
    settings = get_settings()
    dataset = _read_json(settings.curated_crossings_geojson_path)
    station_graph = get_station_graph_service()
    predictor = get_predictor_service()
    print("export_mobile_bundle_stage station_lookup", flush=True)
    station_lookup_by_id = await station_graph.get_station_lookup_by_id()
    print("export_mobile_bundle_stage timetable_snapshot", flush=True)
    timetables, timetable_snapshot = await _load_timetable_snapshot(enabled=use_timetable_snapshot)
    print(f"export_mobile_bundle_stage crossings features={len(dataset.get('features', []))} timetables={len(timetables)}", flush=True)

    crossings: list[dict[str, Any]] = []
    unavailable_count = 0
    runtime_ratio_count = 0
    runtime_ratio_rejection_count = 0
    station_pair_projections: dict[str, dict[str, Any]] = {}
    station_pair_projection_rejections: dict[str, dict[str, Any]] = {}
    station_projection_candidate_cache: dict[tuple[str, str], list[str]] = {}

    def add_station_projection(*, station_id: str, upstream_station_id: str, downstream_station_id: str) -> None:
        key = f"{station_id}|{upstream_station_id}|{downstream_station_id}"
        if key in station_pair_projections or key in station_pair_projection_rejections:
            return
        station = station_lookup_by_id.get(station_id)
        position = _station_position(station)
        if position is None:
            station_pair_projection_rejections[key] = {
                "station_id": station_id,
                "upstream_station_id": upstream_station_id,
                "downstream_station_id": downstream_station_id,
                "source": "unavailable",
                "confidence": "low",
                "note": "Station projection skipped because the station has no usable coordinates.",
            }
            return
        ratio, source, confidence, note = station_graph.resolve_runtime_ratio_for_station_pair(
            {
                "crossing_id": f"station-projection:{station_id}",
                "geometry": {"lon": position["PositionLon"], "lat": position["PositionLat"]},
            },
            upstream_station_id=upstream_station_id,
            downstream_station_id=downstream_station_id,
            station_lookup_by_id=station_lookup_by_id,
        )
        if source == "osm_path" and ratio is not None and 0.0 < float(ratio) < 1.0:
            station_pair_projections[key] = {
                "station_id": station_id,
                "upstream_station_id": upstream_station_id,
                "downstream_station_id": downstream_station_id,
                "ratio": max(0.0, min(1.0, float(ratio))),
                "source": "osm_path",
                "confidence": confidence or "high",
                "note": note,
            }
            return
        station_pair_projection_rejections[key] = {
            "station_id": station_id,
            "upstream_station_id": upstream_station_id,
            "downstream_station_id": downstream_station_id,
            "source": source or "unavailable",
            "confidence": confidence or "low",
            "note": note,
        }

    for feature in dataset.get("features", []):
        properties = dict(feature.get("properties") or {})
        geometry = _feature_geometry(feature)
        if geometry is not None:
            properties["geometry"] = dict(geometry)

        enriched = await station_graph.enrich_crossing_properties(properties)
        crossing_id = str(feature.get("id") or enriched.get("crossing_id") or "").strip()
        if not crossing_id or geometry is None:
            continue

        ratios: dict[str, dict[str, Any]] = {}
        ratio_rejections: dict[str, dict[str, Any]] = {}
        station_a_id = enriched.get("station_a_id")
        station_b_id = enriched.get("station_b_id")
        segment_ratio = enriched.get("segment_ratio")
        ratio_source = enriched.get("ratio_source")
        segment_confidence = enriched.get("segment_confidence")
        segment_note = enriched.get("segment_confidence_reason")

        _add_ratio(
            ratios,
            upstream_station_id=station_a_id,
            downstream_station_id=station_b_id,
            ratio=segment_ratio,
            source=ratio_source,
            confidence=segment_confidence,
            note=segment_note,
        )
        if segment_ratio is not None:
            _add_ratio(
                ratios,
                upstream_station_id=station_b_id,
                downstream_station_id=station_a_id,
                ratio=1.0 - float(segment_ratio),
                source=ratio_source,
                confidence=segment_confidence,
                note="Reverse direction of the selected OSM station-pair ratio.",
            )

        crossing_for_projection = {
            **enriched,
            "crossing_id": crossing_id,
            "geometry": geometry,
            "osm_rail_way_ids": enriched.get("osm_rail_way_ids") or [],
        }
        if timetables and station_a_id and station_b_id:
            prepared = predictor._prepare_timetables_for_crossing(
                timetables,
                str(station_a_id),
                str(station_b_id),
                station_lookup_by_id=station_lookup_by_id,
            )
            pair_stats: dict[tuple[str, str], dict[str, int]] = {}
            for candidate in prepared.all_candidates:
                upstream_id = str(candidate.upstream.get("StationID") or "").strip()
                downstream_id = str(candidate.downstream.get("StationID") or "").strip()
                if not upstream_id or not downstream_id:
                    continue
                key = (upstream_id, downstream_id)
                span = max(int(candidate.downstream_index) - int(candidate.upstream_index), 0)
                stats = pair_stats.setdefault(key, {"count": 0, "span": span})
                stats["count"] += 1
                stats["span"] = min(stats["span"], span)
            pair_keys = sorted(pair_stats, key=lambda key: (pair_stats[key]["span"], -pair_stats[key]["count"], key[0], key[1]))[:MAX_TIMETABLE_RUNTIME_PAIRS_PER_CROSSING]
            for upstream_id, downstream_id in pair_keys:
                if _ratio_key(upstream_id, downstream_id) not in ratios:
                    ratio, source, confidence, note = station_graph.resolve_runtime_ratio_for_station_pair(
                        crossing_for_projection,
                        upstream_station_id=upstream_id,
                        downstream_station_id=downstream_id,
                        station_lookup_by_id=station_lookup_by_id,
                    )
                    before_count = len(ratios)
                    _add_ratio(
                        ratios,
                        upstream_station_id=upstream_id,
                        downstream_station_id=downstream_id,
                        ratio=ratio,
                        source=source,
                        confidence=confidence,
                        note=note,
                    )
                    if len(ratios) == before_count:
                        _add_rejection(
                            ratio_rejections,
                            upstream_station_id=upstream_id,
                            downstream_station_id=downstream_id,
                            source=source,
                            confidence=confidence,
                            note=note,
                        )
                candidate_cache_key = (upstream_id, downstream_id)
                candidate_station_ids = station_projection_candidate_cache.get(candidate_cache_key)
                if candidate_station_ids is None:
                    candidate_station_ids = _candidate_station_projection_ids(
                        upstream_station_id=upstream_id,
                        downstream_station_id=downstream_id,
                        station_lookup_by_id=station_lookup_by_id,
                    )
                    station_projection_candidate_cache[candidate_cache_key] = candidate_station_ids
                for station_id in candidate_station_ids:
                    add_station_projection(station_id=station_id, upstream_station_id=upstream_id, downstream_station_id=downstream_id)

        runtime_ratio_count += len(ratios)
        runtime_ratio_rejection_count += len(ratio_rejections)
        if ratio_source != "osm_path" or segment_ratio is None:
            unavailable_count += 1

        station_a = station_lookup_by_id.get(str(station_a_id or ""))
        station_b = station_lookup_by_id.get(str(station_b_id or ""))
        crossings.append(
            {
                "id": crossing_id,
                "name": enriched.get("name"),
                "line": enriched.get("line"),
                "county": enriched.get("county"),
                "road_type": enriched.get("road_type"),
                "km_marker": enriched.get("km_marker"),
                "station_pair_text": enriched.get("station_pair_text") or enriched.get("query_station_pair_text"),
                "station_pair_source": enriched.get("station_pair_source"),
                "geometry": geometry,
                "geolocation_confidence": enriched.get("geolocation_confidence"),
                "segment_ratio": segment_ratio,
                "ratio_source": ratio_source,
                "segment_confidence": segment_confidence,
                "segment_confidence_reason": segment_note,
                "station_a": {
                    "id": station_a_id,
                    "name": _station_name(station_a) or enriched.get("station_a_name"),
                    "position": _compact_position((station_a or {}).get("StationPosition") or enriched.get("station_a_position")),
                    "uk_primary": enriched.get("station_a_uk_primary"),
                    "uk_values": enriched.get("station_a_uk_values") or [],
                },
                "station_b": {
                    "id": station_b_id,
                    "name": _station_name(station_b) or enriched.get("station_b_name"),
                    "position": _compact_position((station_b or {}).get("StationPosition") or enriched.get("station_b_position")),
                    "uk_primary": enriched.get("station_b_uk_primary"),
                    "uk_values": enriched.get("station_b_uk_values") or [],
                },
                "osm_rail_way_ids": enriched.get("osm_rail_way_ids") or [],
                "runtime_ratios": ratios,
                "runtime_ratio_rejections": ratio_rejections,
            }
        )
        if len(crossings) % 10 == 0:
            print(
                "export_mobile_bundle_progress "
                f"crossings={len(crossings)} ratios={runtime_ratio_count} projections={len(station_pair_projections)}",
                flush=True,
            )

    stations = await station_graph.list_station_summaries()
    calibration = _read_json(settings.prediction_calibration_path) if settings.prediction_calibration_path.exists() else {"rules": []}
    payload = {
        "metadata": {
            "schema_version": 2,
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "CrossRadar WebApp curated runtime datasets",
            "crossing_count": len(crossings),
            "station_count": len(stations),
            "runtime_ratio_count": runtime_ratio_count,
            "runtime_ratio_rejection_count": runtime_ratio_rejection_count,
            "runtime_unavailable_count": unavailable_count,
            "station_pair_projection_count": len(station_pair_projections),
            "station_pair_projection_rejection_count": len(station_pair_projection_rejections),
            "tdx_timetable_snapshot": timetable_snapshot,
            "runtime_ratio_scope": "anchor_and_timetable_stop_pairs_with_station_projection_ratios",
            "osm_attribution": "Contains OpenStreetMap-derived level-crossing and rail-path data. OpenStreetMap contributors, ODbL.",
        },
        "crossings": crossings,
        "stations": stations,
        "station_pair_projections": station_pair_projections,
        "calibration": calibration,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the compact CrossRadar mobile asset bundle.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../PhoneApp/assets/data/crossradar_mobile_bundle.json"),
        help="Output JSON path relative to WebApp when run from WebApp/.",
    )
    parser.add_argument(
        "--skip-timetable-snapshot",
        action="store_true",
        help="Export schema v2 with anchor ratios only when the TDX timetable cache is unavailable or too slow.",
    )
    args = parser.parse_args()
    payload = asyncio.run(export_mobile_bundle(args.output, use_timetable_snapshot=not args.skip_timetable_snapshot))
    metadata = payload["metadata"]
    print(
        "exported_mobile_bundle "
        f"crossings={metadata['crossing_count']} "
        f"stations={metadata['station_count']} "
        f"ratios={metadata['runtime_ratio_count']} "
        f"projections={metadata['station_pair_projection_count']} "
        f"unavailable={metadata['runtime_unavailable_count']} "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()