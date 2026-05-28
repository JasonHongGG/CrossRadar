from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import get_settings
from backend.app.clients.tdx_auth import TdxTokenManager
from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.crossing_scraper import TraOfficialCrossingScraper
from backend.app.services.osm_enricher import OsmEnricher
from backend.app.services.prediction_calibration import PredictionCalibrationService
from backend.app.services.predictor import PredictorService
from backend.app.services.rail_path import RailPathService
from backend.app.services.station_graph import StationGraphService
from backend.app.services.travel_profile import TravelProfileService
from backend.app.utils import parse_time_on_date


async def main() -> None:
    settings = get_settings()
    observations_payload = json.loads(settings.manual_passage_observations_path.read_text(encoding="utf-8"))
    observations = observations_payload.get("observations", [])

    token_manager = TdxTokenManager(settings)
    tdx_client = TdxTraClient(token_manager, settings)
    rail_path_service = RailPathService(settings)
    station_graph_service = StationGraphService(tdx_client, rail_path_service, settings)
    scraper = TraOfficialCrossingScraper(settings)
    osm_enricher = OsmEnricher(settings)
    catalog_service = CrossingCatalogService(scraper, osm_enricher, settings, station_graph_service=station_graph_service)
    travel_profile_service = TravelProfileService()
    calibration_service = PredictionCalibrationService(travel_profile_service, settings)
    predictor = PredictorService(
        tdx_client,
        catalog_service,
        station_graph_service,
        travel_profile_service,
        calibration_service,
    )

    timetables_result = await tdx_client.get_today_timetables_snapshot(force_refresh=False)
    train_infos_result = await tdx_client.get_today_train_infos_snapshot(force_refresh=False)
    liveboards_result = await tdx_client.get_liveboards_snapshot(force_refresh=False)
    train_info_by_train_no = predictor._build_train_info_index(train_infos_result.value)
    liveboard_by_train_no = build_liveboard_index(liveboards_result.value)
    station_lookup_by_id = await station_graph_service.get_station_lookup_by_id()

    crossing_cache: dict[str, dict[str, Any]] = {}
    prepared_cache: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []

    for observation in observations:
        service_date_text = str(observation.get("service_date") or "")
        observation_date = date.fromisoformat(service_date_text)
        if observation_date != date.today():
            rows.append(
                {
                    "id": observation.get("id"),
                    "status": "skipped",
                    "reason": f"Only same-day observations can be rebuilt from current timetable snapshots; got {service_date_text}.",
                }
            )
            continue

        crossing_id = str(observation.get("crossing_id") or "")
        if crossing_id not in crossing_cache:
            feature = await catalog_service.get_crossing(crossing_id)
            if feature is None:
                rows.append({"id": observation.get("id"), "status": "missing_crossing", "reason": f"Unknown crossing {crossing_id}."})
                continue
            properties = dict(feature.get("properties", {}))
            if feature.get("geometry") is not None:
                coordinates = feature["geometry"].get("coordinates") or [None, None]
                if coordinates[0] is not None and coordinates[1] is not None:
                    properties["geometry"] = {"lon": coordinates[0], "lat": coordinates[1]}
            properties = await station_graph_service.enrich_crossing_properties(properties)
            crossing_cache[crossing_id] = properties
        crossing = crossing_cache[crossing_id]

        if crossing_id not in prepared_cache:
            prepared_cache[crossing_id] = predictor._prepare_timetables_for_crossing(
                timetables_result.value,
                crossing.get("station_a_id"),
                crossing.get("station_b_id"),
                station_lookup_by_id=station_lookup_by_id,
            )
        prepared = prepared_cache[crossing_id]

        train_no = str(observation.get("train_no") or "")
        candidates = prepared.by_train_no.get(train_no)
        if not candidates:
            rows.append({"id": observation.get("id"), "status": "missing_timetable", "reason": f"No timetable candidate for train {train_no}."})
            continue
        candidate = candidates[0]
        timetable = candidate.timetable
        upstream = candidate.upstream
        downstream = candidate.downstream
        train_info = timetable.get("TrainInfo", {})
        upstream_departure = parse_time_on_date(observation_date, upstream.get("DepartureTime") or upstream.get("ArrivalTime"))
        downstream_arrival = parse_time_on_date(observation_date, downstream.get("ArrivalTime") or downstream.get("DepartureTime"))
        observed_passage = parse_time_on_date(observation_date, observation.get("observed_passage_time"))
        if upstream_departure is None or downstream_arrival is None or observed_passage is None:
            rows.append({"id": observation.get("id"), "status": "invalid_time", "reason": "Observation or timetable time could not be parsed."})
            continue

        delay_minutes, delay_source = predictor._resolve_delay_minutes(train_no, train_info_by_train_no=train_info_by_train_no)
        runtime_timing = predictor._estimate_prediction_timing(
            crossing,
            train_no=train_no,
            train_type_name=predictor._extract_train_type(train_info.get("TrainTypeName") or observation.get("train_type")),
            upstream_station_id=upstream.get("StationID"),
            downstream_station_id=downstream.get("StationID"),
            upstream=upstream,
            downstream=downstream,
            upstream_departure=upstream_departure,
            downstream_arrival=downstream_arrival,
            delay_minutes=delay_minutes,
            delay_source=delay_source,
            direction=candidate.direction,
            station_lookup_by_id=station_lookup_by_id,
            data_basis="timetable",
            apply_calibration=False,
        )
        if runtime_timing is None:
            rows.append({"id": observation.get("id"), "status": "missing_ratio", "reason": "No runtime OSM segment ratio was available."})
            continue

        selected_liveboard = select_liveboard_record(liveboard_by_train_no.get(train_no, []))
        benchmark_delay_minutes, benchmark_delay_source = resolve_benchmark_delay(
            train_no,
            train_info_by_train_no=train_info_by_train_no,
            liveboard=selected_liveboard,
        )
        benchmark_timing = runtime_timing
        if benchmark_delay_minutes != delay_minutes or benchmark_delay_source != delay_source:
            recalculated = predictor._estimate_prediction_timing(
                crossing,
                train_no=train_no,
                train_type_name=predictor._extract_train_type(train_info.get("TrainTypeName") or observation.get("train_type")),
                upstream_station_id=upstream.get("StationID"),
                downstream_station_id=downstream.get("StationID"),
                upstream=upstream,
                downstream=downstream,
                upstream_departure=upstream_departure,
                downstream_arrival=downstream_arrival,
                delay_minutes=benchmark_delay_minutes,
                delay_source=benchmark_delay_source,
                direction=candidate.direction,
                station_lookup_by_id=station_lookup_by_id,
                data_basis="timetable",
                apply_calibration=False,
            )
            if recalculated is not None:
                benchmark_timing = recalculated

        runtime_error_seconds = int(round((runtime_timing.eta - observed_passage).total_seconds()))
        benchmark_error_seconds = int(round((benchmark_timing.eta - observed_passage).total_seconds()))
        rows.append(
            {
                "id": observation.get("id"),
                "status": "ok",
                "crossing_id": crossing_id,
                "train_no": train_no,
                "direction": candidate.direction,
                "upstream_station_id": upstream.get("StationID"),
                "downstream_station_id": downstream.get("StationID"),
                "train_type": predictor._extract_train_type(train_info.get("TrainTypeName") or observation.get("train_type")),
                "train_type_family": runtime_timing.train_type_family,
                "prediction_method": runtime_timing.timing_model,
                "predicted_eta": runtime_timing.eta.isoformat(),
                "runtime_delay_minutes": delay_minutes,
                "runtime_delay_source": delay_source,
                "benchmark_predicted_eta": benchmark_timing.eta.isoformat(),
                "benchmark_delay_minutes": benchmark_delay_minutes,
                "benchmark_delay_source": benchmark_delay_source,
                "tdx_liveboard_station_id": selected_liveboard.get("StationID") if selected_liveboard else None,
                "tdx_liveboard_station_name": ((selected_liveboard.get("StationName") or {}).get("Zh_tw") if selected_liveboard else None),
                "tdx_liveboard_delay_minutes": int(selected_liveboard.get("DelayTime")) if selected_liveboard and selected_liveboard.get("DelayTime") is not None else None,
                "tdx_liveboard_update_time": selected_liveboard.get("UpdateTime") if selected_liveboard else None,
                "tdx_train_info_delay_minutes": int(train_info_by_train_no[train_no].get("DelayTime")) if train_no in train_info_by_train_no and train_info_by_train_no[train_no].get("DelayTime") is not None else None,
                "tdx_train_info_update_time": train_info_by_train_no[train_no].get("UpdateTime") if train_no in train_info_by_train_no else None,
                "observed_eta": observed_passage.isoformat(),
                "runtime_error_seconds": runtime_error_seconds,
                "benchmark_error_seconds": benchmark_error_seconds,
                "rule_error_seconds": benchmark_error_seconds,
                "calibration_eligible": bool(observation.get("calibration_eligible", True)),
            }
        )

    rules = build_rules(rows)
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    runtime_errors = [abs(int(row["runtime_error_seconds"])) for row in ok_rows]
    benchmark_rows = [row for row in ok_rows if row.get("benchmark_error_seconds") is not None]
    benchmark_errors = [abs(int(row["benchmark_error_seconds"])) for row in benchmark_rows]
    payload = {
        "metadata": {
            "generated_from": str(settings.manual_passage_observations_path.relative_to(ROOT_DIR)),
            "generated_on": date.today().isoformat(),
            "observation_count": len(observations),
            "usable_count": len(ok_rows),
        },
        "baseline": {
            "runtime_mean_absolute_error_seconds": round(sum(runtime_errors) / len(runtime_errors), 1) if runtime_errors else None,
            "runtime_max_absolute_error_seconds": max(runtime_errors) if runtime_errors else None,
            "benchmark_mean_absolute_error_seconds": round(sum(benchmark_errors) / len(benchmark_errors), 1) if benchmark_errors else None,
            "benchmark_max_absolute_error_seconds": max(benchmark_errors) if benchmark_errors else None,
            "benchmark_coverage_count": len(benchmark_rows),
        },
        "rules": rules,
        "observations": rows,
    }
    settings.prediction_calibration_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {settings.prediction_calibration_path}")
    print(json.dumps(payload["baseline"], ensure_ascii=False, indent=2))
    print(f"rules={len(rules)}")


def build_rules(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible_rows = [row for row in rows if row.get("status") == "ok" and row.get("calibration_eligible")]
    rules: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    family_groups: dict[tuple[str, int, str, str], list[dict[str, Any]]] = defaultdict(list)
    segment_groups: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible_rows:
        family_groups[(row["crossing_id"], row["direction"], row["upstream_station_id"], row["train_type_family"])].append(row)
        segment_groups[(row["crossing_id"], row["direction"], row["upstream_station_id"])].append(row)

    for (crossing_id, direction, upstream_station_id, train_type_family), group in family_groups.items():
        candidate = build_rule_candidate(group, spread_limit_seconds=25, minimum_inliers=2)
        if candidate is None:
            continue
        rule = {
            "id": f"{crossing_id}:{direction}:{upstream_station_id}:{train_type_family}",
            "match": {
                "crossing_id": crossing_id,
                "direction": direction,
                "upstream_station_id": upstream_station_id,
                "train_type_family": train_type_family,
            },
            **candidate,
        }
        rules.append(rule)
        used_ids.update(str(row["id"]) for row in candidate["inlier_rows"])

    for (crossing_id, direction, upstream_station_id), group in segment_groups.items():
        remaining = [row for row in group if str(row["id"]) not in used_ids]
        candidate = build_rule_candidate(remaining, spread_limit_seconds=30, minimum_inliers=3)
        if candidate is None:
            continue
        rules.append(
            {
                "id": f"{crossing_id}:{direction}:{upstream_station_id}:segment",
                "match": {
                    "crossing_id": crossing_id,
                    "direction": direction,
                    "upstream_station_id": upstream_station_id,
                },
                **candidate,
            }
        )

    for rule in rules:
        rule.pop("inlier_rows", None)
    return rules


def build_rule_candidate(group: list[dict[str, Any]], *, spread_limit_seconds: int, minimum_inliers: int) -> dict[str, Any] | None:
    if len(group) < minimum_inliers:
        return None
    errors = [int(row["rule_error_seconds"]) for row in group]
    median_error = float(median(errors))
    inliers = [row for row in group if abs(int(row["rule_error_seconds"]) - median_error) <= 30]
    if len(inliers) < minimum_inliers:
        return None
    inlier_errors = [int(row["rule_error_seconds"]) for row in inliers]
    spread = max(inlier_errors) - min(inlier_errors)
    if spread > spread_limit_seconds:
        return None
    offset_seconds = int(round(-float(median(inlier_errors))))
    return {
        "offset_seconds": offset_seconds,
        "count": len(group),
        "inlier_count": len(inliers),
        "median_error_seconds": int(round(float(median(inlier_errors)))),
        "spread_seconds": spread,
        "inlier_rows": [{"id": row["id"], "error_seconds": row["rule_error_seconds"]} for row in inliers],
    }


def build_liveboard_index(liveboards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for liveboard in liveboards:
        train_no = str(liveboard.get("TrainNo") or "").strip()
        if not train_no:
            continue
        index[train_no].append(liveboard)
    return index


def select_liveboard_record(liveboards: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not liveboards:
        return None
    return max(liveboards, key=lambda item: parse_update_time(item.get("UpdateTime")))


def resolve_benchmark_delay(
    train_no: str,
    *,
    train_info_by_train_no: dict[str, dict[str, Any]],
    liveboard: dict[str, Any] | None,
) -> tuple[int, str]:
    train_info = train_info_by_train_no.get(train_no)
    if train_info is not None and train_info.get("DelayTime") is not None:
        return (int(train_info.get("DelayTime") or 0), "train_info")
    if liveboard is not None and liveboard.get("DelayTime") is not None:
        return (int(liveboard.get("DelayTime") or 0), "liveboard")
    return (0, "none")


def parse_update_time(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min


if __name__ == "__main__":
    asyncio.run(main())
