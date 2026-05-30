from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Any

from backend.app.dependencies import get_predictor_service, get_settings, get_station_graph_service, get_tdx_client


_UK_PRIMARY_PATTERN = re.compile(r"^(?P<line>.+?)\s+K\s*(?P<km>\d+)\s*\+\s*(?P<meter>\d+)$")
_RAIL_PATH_STATION_MAX_SNAP_DISTANCE_METERS = 1_500.0
_RAIL_PATH_STATION_MAX_SNAP_CANDIDATES = 8
_MAX_STATION_PROJECTION_CANDIDATES_PER_PAIR = 16

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_bundle_calibration(*, prediction_calibration_path: Path) -> dict[str, Any]:
    calibration = _read_json(prediction_calibration_path) if prediction_calibration_path.exists() else {"rules": []}
    replay_path = prediction_calibration_path.parent / "prediction_observation_replay.json"
    if not replay_path.exists():
        return calibration

    replay_payload = _read_json(replay_path)
    merged = dict(calibration)
    for key in ("metadata", "baseline", "readiness", "observations"):
        if key in replay_payload:
            merged[key] = replay_payload[key]

    metadata = dict(merged.get("metadata") or {})
    replay_metadata = replay_payload.get("metadata") or {}
    metadata["observation_mode"] = replay_metadata.get("mode") or metadata.get("observation_mode")
    metadata["replay_generated_on"] = replay_metadata.get("generated_on")
    replayed_dates = replay_metadata.get("replayed_service_dates")
    if replayed_dates is not None:
        metadata["replayed_service_dates"] = replayed_dates
    merged["metadata"] = metadata
    return merged


def _build_prediction_contract_metadata(
    *,
    calibration: dict[str, Any],
    timetable_snapshot: dict[str, Any],
    runtime_ratio_count: int,
    runtime_ratio_rejection_count: int,
    station_pair_projection_count: int,
    station_pair_projection_rejection_count: int,
    runtime_unavailable_count: int,
) -> dict[str, Any]:
    calibration_rules = calibration.get("rules") or []
    calibration_observations = calibration.get("observations") or []
    readiness = calibration.get("readiness") or {}
    return {
        "version": 1,
        "runtime_independence": "PhoneApp predicts locally from this bundle plus direct TDX snapshots; it must not call WebApp prediction APIs.",
        "railway_time_zone": "Asia/Taipei",
        "snapshot_required_sources": ["liveboards", "timetables", "train_info"],
        "snapshot_incomplete_behavior": "prediction_unavailable",
        "runtime_ratio_source": "osm_path_only",
        "runtime_ratio_scope": "anchor_and_all_timetable_stop_pairs_with_full_station_projection_ratios",
        "runtime_ratio_count": runtime_ratio_count,
        "runtime_ratio_rejection_count": runtime_ratio_rejection_count,
        "runtime_unavailable_count": runtime_unavailable_count,
        "station_pair_projection_count": station_pair_projection_count,
        "station_pair_projection_rejection_count": station_pair_projection_rejection_count,
        "calibration_rule_count": len(calibration_rules),
        "calibration_observation_count": len(calibration_observations),
        "calibration_family_ready_count": readiness.get("family_ready_count", 0),
        "calibration_segment_ready_count": readiness.get("segment_ready_count", 0),
        "tdx_timetable_snapshot": timetable_snapshot,
        "trace_required_fields": [
            "service_date",
            "train_no",
            "upstream_station_id",
            "downstream_station_id",
            "ratio",
            "delay_seconds",
            "delay_source",
            "travel_profile_id",
            "time_fraction",
            "timing_model",
            "calibration_offset_seconds",
            "eta",
        ],
    }


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


def _station_chainage(station: dict[str, Any] | None) -> tuple[str, int] | None:
    uk_primary = str((station or {}).get("UK_primary") or "").strip()
    if not uk_primary:
        return None
    normalized = " ".join(uk_primary.split())
    match = _UK_PRIMARY_PATTERN.match(normalized)
    if match is None:
        return None
    return (match.group("line").strip(), int(match.group("km")) * 1000 + int(match.group("meter")))


def _corridor_station_projection_ids(
    *,
    upstream_station_id: str,
    downstream_station_id: str,
    station_lookup_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    upstream_chainage = _station_chainage(station_lookup_by_id.get(upstream_station_id))
    downstream_chainage = _station_chainage(station_lookup_by_id.get(downstream_station_id))
    if upstream_chainage is None or downstream_chainage is None:
        return []
    if upstream_chainage[0] != downstream_chainage[0]:
        return []

    line_name = upstream_chainage[0]
    lower_bound = min(upstream_chainage[1], downstream_chainage[1])
    upper_bound = max(upstream_chainage[1], downstream_chainage[1])
    midpoint = (lower_bound + upper_bound) / 2.0
    station_ids: list[tuple[int, str]] = []
    for station_id, station in station_lookup_by_id.items():
        if station_id in {upstream_station_id, downstream_station_id}:
            continue
        station_chainage = _station_chainage(station)
        if station_chainage is None or station_chainage[0] != line_name:
            continue
        station_meters = station_chainage[1]
        if not (lower_bound < station_meters < upper_bound):
            continue
        station_ids.append((abs(int(round(station_meters - midpoint))), str(station_id)))
    station_ids.sort(key=lambda item: (item[0], item[1]))
    return [station_id for _, station_id in station_ids]


def _station_snap_candidates(*, rail_path_service: Any, station: dict[str, Any] | None) -> list[Any]:
    if rail_path_service is None:
        return []
    position = _station_position(station)
    if position is None:
        return []
    return rail_path_service._snap_point_candidates(
        position.get("PositionLon"),
        position.get("PositionLat"),
        max_snap_distance_meters=_RAIL_PATH_STATION_MAX_SNAP_DISTANCE_METERS,
        max_candidates=_RAIL_PATH_STATION_MAX_SNAP_CANDIDATES,
    )


def _pair_path_spec(
    *,
    rail_path_service: Any,
    rail_graph: Any,
    segments_by_nodes: dict[frozenset[int], set[int]],
    upstream_snaps: list[Any],
    downstream_snaps: list[Any],
) -> dict[str, Any] | None:
    best_score: float | None = None
    best_spec: dict[str, Any] | None = None
    for upstream_snap in upstream_snaps:
        for downstream_snap in downstream_snaps:
            direct_distance: float | None = None
            direct_spec: dict[str, Any] | None = None
            if upstream_snap.segment_id == downstream_snap.segment_id:
                direct_distance = abs(
                    upstream_snap.distance_from_start_meters - downstream_snap.distance_from_start_meters
                )
                direct_spec = {
                    "distance": direct_distance,
                    "segment_ids": {upstream_snap.segment_id},
                    "way_ids": {rail_graph.segments[upstream_snap.segment_id].way_id},
                }

            graph_result = rail_path_service._dijkstra_path(
                [
                    (upstream_snap.start_node, upstream_snap.distance_from_start_meters),
                    (upstream_snap.end_node, upstream_snap.distance_to_end_meters),
                ],
                {
                    downstream_snap.start_node: downstream_snap.distance_from_start_meters,
                    downstream_snap.end_node: downstream_snap.distance_to_end_meters,
                },
            )
            spec = direct_spec
            if graph_result is not None:
                graph_distance, node_path = graph_result
                if direct_spec is None or direct_distance is None or direct_distance > graph_distance:
                    segment_ids = {upstream_snap.segment_id, downstream_snap.segment_id}
                    for start_node, end_node in zip(node_path, node_path[1:]):
                        segment_ids.update(segments_by_nodes.get(frozenset((start_node, end_node)), set()))
                    spec = {
                        "distance": graph_distance,
                        "segment_ids": segment_ids,
                        "way_ids": {rail_graph.segments[segment_id].way_id for segment_id in segment_ids},
                    }

            if spec is None:
                continue
            score = (
                float(upstream_snap.snap_distance_meters)
                + float(downstream_snap.snap_distance_meters)
                + float(spec["distance"]) * 0.25
            )
            if best_score is None or score < best_score:
                best_score = score
                best_spec = spec
    return best_spec


def _path_segment_station_projection_ids(
    *,
    upstream_station_id: str,
    downstream_station_id: str,
    rail_path_service: Any,
    rail_graph: Any,
    segments_by_nodes: dict[frozenset[int], set[int]],
    pair_path_spec_cache: dict[tuple[str, str], dict[str, Any] | None],
    station_snap_candidates_by_id: dict[str, list[Any]],
) -> list[str]:
    if rail_path_service is None or rail_graph is None:
        return []

    pair_key = (upstream_station_id, downstream_station_id)
    pair_spec = pair_path_spec_cache.get(pair_key)
    if pair_spec is None and pair_key not in pair_path_spec_cache:
        pair_spec = _pair_path_spec(
            rail_path_service=rail_path_service,
            rail_graph=rail_graph,
            segments_by_nodes=segments_by_nodes,
            upstream_snaps=station_snap_candidates_by_id.get(upstream_station_id, []),
            downstream_snaps=station_snap_candidates_by_id.get(downstream_station_id, []),
        )
        pair_path_spec_cache[pair_key] = pair_spec
    if not pair_spec:
        return []

    path_segment_ids = pair_spec["segment_ids"]
    path_way_ids = pair_spec.get("way_ids") or set()
    candidate_station_ids: list[str] = []
    for station_id, station_snaps in station_snap_candidates_by_id.items():
        if station_id in {upstream_station_id, downstream_station_id}:
            continue
        if any(
            station_snap.segment_id in path_segment_ids or station_snap.way_id in path_way_ids
            for station_snap in station_snaps
        ):
            candidate_station_ids.append(station_id)
    return candidate_station_ids


def _bounded_station_projection_candidate_ids(
    *,
    path_station_ids: list[str],
    corridor_station_ids: list[str],
    timetable_station_ids: set[str],
    calibration_station_ids: list[str],
) -> list[str]:
    pinned = list(dict.fromkeys([*sorted(timetable_station_ids), *calibration_station_ids]))
    pinned_set = set(pinned)
    fallback = [
        station_id
        for station_id in dict.fromkeys([*path_station_ids, *corridor_station_ids])
        if station_id not in pinned_set
    ]
    limit = max(_MAX_STATION_PROJECTION_CANDIDATES_PER_PAIR - len(pinned), 0)
    return [*pinned, *fallback[:limit]]


def _calibration_projection_requests(calibration: dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    requests: dict[tuple[str, str], set[str]] = defaultdict(set)
    for observation in calibration.get("observations", []):
        if observation.get("status") != "ok":
            continue
        station_id = str(observation.get("tdx_liveboard_station_id") or "").strip()
        upstream_station_id = str(observation.get("upstream_station_id") or "").strip()
        downstream_station_id = str(observation.get("downstream_station_id") or "").strip()
        if not station_id or not upstream_station_id or not downstream_station_id:
            continue
        if station_id in {upstream_station_id, downstream_station_id}:
            continue
        requests[(upstream_station_id, downstream_station_id)].add(station_id)
    return {key: sorted(station_ids) for key, station_ids in requests.items()}


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
    calibration = _load_bundle_calibration(prediction_calibration_path=settings.prediction_calibration_path)
    calibration_projection_requests = _calibration_projection_requests(calibration)
    station_graph = get_station_graph_service()
    predictor = get_predictor_service()
    print("export_mobile_bundle_stage station_lookup", flush=True)
    station_lookup_by_id = await station_graph.get_station_lookup_by_id()
    rail_path_service = station_graph.rail_path_service
    rail_graph = rail_path_service._graph if rail_path_service is not None else None
    path_segments_by_nodes: dict[frozenset[int], set[int]] = defaultdict(set)
    if rail_graph is not None:
        for segment in rail_graph.segments:
            path_segments_by_nodes[frozenset((segment.start_node, segment.end_node))].add(segment.segment_id)
    station_snap_candidates_by_id = {
        str(station_id): _station_snap_candidates(rail_path_service=rail_path_service, station=station)
        for station_id, station in station_lookup_by_id.items()
    }
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
    pair_path_spec_cache: dict[tuple[str, str], dict[str, Any] | None] = {}

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
            pair_station_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
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
                for stop in (candidate.timetable.get("StopTimes") or [])[int(candidate.upstream_index) + 1 : int(candidate.downstream_index)]:
                    station_id = str(stop.get("StationID") or "").strip()
                    if station_id and station_id not in {upstream_id, downstream_id}:
                        pair_station_ids[key].add(station_id)
            pair_keys = sorted(pair_stats, key=lambda key: (pair_stats[key]["span"], -pair_stats[key]["count"], key[0], key[1]))
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
                    candidate_station_ids = _bounded_station_projection_candidate_ids(
                        path_station_ids=_path_segment_station_projection_ids(
                            upstream_station_id=upstream_id,
                            downstream_station_id=downstream_id,
                            rail_path_service=rail_path_service,
                            rail_graph=rail_graph,
                            segments_by_nodes=path_segments_by_nodes,
                            pair_path_spec_cache=pair_path_spec_cache,
                            station_snap_candidates_by_id=station_snap_candidates_by_id,
                        ),
                        corridor_station_ids=_corridor_station_projection_ids(
                            upstream_station_id=upstream_id,
                            downstream_station_id=downstream_id,
                            station_lookup_by_id=station_lookup_by_id,
                        ),
                        timetable_station_ids=pair_station_ids.get(candidate_cache_key, set()),
                        calibration_station_ids=calibration_projection_requests.get(candidate_cache_key, []),
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
    prediction_contract = _build_prediction_contract_metadata(
        calibration=calibration,
        timetable_snapshot=timetable_snapshot,
        runtime_ratio_count=runtime_ratio_count,
        runtime_ratio_rejection_count=runtime_ratio_rejection_count,
        station_pair_projection_count=len(station_pair_projections),
        station_pair_projection_rejection_count=len(station_pair_projection_rejections),
        runtime_unavailable_count=unavailable_count,
    )
    payload = {
        "metadata": {
            "schema_version": 3,
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
            "prediction_contract": prediction_contract,
            "runtime_ratio_scope": "anchor_and_all_timetable_stop_pairs_with_full_station_projection_ratios",
            "osm_attribution": "Contains OpenStreetMap-derived level-crossing and rail-path data. OpenStreetMap contributors, ODbL.",
        },
        "crossings": crossings,
        "stations": stations,
        "station_pair_projections": station_pair_projections,
        "station_pair_projection_rejections": station_pair_projection_rejections,
        "calibration": calibration,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the full CrossRadar mobile asset bundle.")
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