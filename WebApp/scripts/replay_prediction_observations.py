from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.clients.tdx_auth import TdxTokenManager
from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.config import get_settings
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.crossing_scraper import TraOfficialCrossingScraper
from backend.app.services.osm_enricher import OsmEnricher
from backend.app.services.prediction_calibration import PredictionCalibrationService
from backend.app.services.predictor import PredictorService
from backend.app.services.rail_path import RailPathService
from backend.app.services.station_graph import StationGraphService
from backend.app.services.travel_profile import TravelProfileService
from build_prediction_calibration import (
    build_calibration_readiness,
    build_liveboard_index,
    build_rules,
    resolve_benchmark_delay,
    select_liveboard_record,
)


async def build_replay_payload() -> dict[str, Any]:
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

        selected_liveboard = select_liveboard_record(liveboard_by_train_no.get(train_no, []))
        liveboard_selection = predictor._select_liveboard_candidate_context(
            crossing,
            [selected_liveboard] if selected_liveboard is not None else [],
            candidates,
            train_info_by_train_no=train_info_by_train_no,
            station_lookup_by_id=station_lookup_by_id,
            reference_date=observation_date,
        )
        liveboard_context = liveboard_selection.context
        liveboard_fallback_reason = liveboard_selection.fallback_reason
        candidate = liveboard_context.candidate if liveboard_context is not None else candidates[0]
        timetable = candidate.timetable
        upstream = candidate.upstream
        downstream = candidate.downstream
        train_info = timetable.get("TrainInfo", {})
        upstream_departure = predictor._parse_liveboard_update_time("1970-01-01T00:00:00+00:00")  # warm parser path
        del upstream_departure
        from backend.app.utils import parse_time_on_date

        upstream_departure = parse_time_on_date(observation_date, upstream.get("DepartureTime") or upstream.get("ArrivalTime"))
        downstream_arrival = parse_time_on_date(observation_date, downstream.get("ArrivalTime") or downstream.get("DepartureTime"))
        observed_passage = parse_time_on_date(observation_date, observation.get("observed_passage_time"))
        if upstream_departure is None or downstream_arrival is None or observed_passage is None:
            rows.append({"id": observation.get("id"), "status": "invalid_time", "reason": "Observation or timetable time could not be parsed."})
            continue

        runtime_projection_reason = liveboard_context.projection_reason if liveboard_context is not None else None
        runtime_selected_liveboard = liveboard_context.liveboard if liveboard_context is not None else selected_liveboard
        if liveboard_context is not None:
            runtime_delay_estimate = liveboard_context.delay_estimate
            runtime_liveboard = liveboard_context.liveboard
        else:
            liveboard_delay_fallback = predictor._resolve_liveboard_delay_fallback(
                [selected_liveboard] if selected_liveboard is not None else []
            )
            if liveboard_delay_fallback is not None:
                runtime_delay_estimate = liveboard_delay_fallback[0]
                runtime_selected_liveboard = liveboard_delay_fallback[1]
            else:
                runtime_delay_estimate = predictor._resolve_delay_estimate(
                    train_no,
                    train_info_by_train_no=train_info_by_train_no,
                )
            runtime_liveboard = None

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
            delay_minutes=runtime_delay_estimate.minutes,
            delay_seconds=runtime_delay_estimate.seconds,
            delay_source=runtime_delay_estimate.source,
            direction=candidate.direction,
            liveboard=runtime_liveboard,
            station_lookup_by_id=station_lookup_by_id,
            data_basis="liveboard" if runtime_liveboard is not None else "timetable",
            apply_calibration=False,
            reference_date=observation_date,
        )
        if runtime_timing is None:
            rows.append({"id": observation.get("id"), "status": "missing_ratio", "reason": "No runtime OSM segment ratio was available."})
            continue

        benchmark_delay_minutes, benchmark_delay_seconds, benchmark_delay_source = resolve_benchmark_delay(
            train_no,
            train_info_by_train_no=train_info_by_train_no,
            liveboard=selected_liveboard,
            liveboard_context=liveboard_context,
        )
        benchmark_timing = runtime_timing
        if benchmark_delay_seconds != runtime_delay_estimate.seconds or benchmark_delay_source != runtime_delay_estimate.source:
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
                delay_seconds=benchmark_delay_seconds,
                delay_source=benchmark_delay_source,
                direction=candidate.direction,
                liveboard=selected_liveboard if liveboard_context is not None else None,
                station_lookup_by_id=station_lookup_by_id,
                data_basis="liveboard" if liveboard_context is not None else "timetable",
                apply_calibration=False,
                reference_date=observation_date,
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
                "service_date": service_date_text,
                "train_no": train_no,
                "direction": candidate.direction,
                "upstream_station_id": upstream.get("StationID"),
                "downstream_station_id": downstream.get("StationID"),
                "train_type": predictor._extract_train_type(train_info.get("TrainTypeName") or observation.get("train_type")),
                "train_type_family": runtime_timing.train_type_family,
                "prediction_method": runtime_timing.timing_model,
                "predicted_eta": runtime_timing.eta.isoformat(),
                "runtime_delay_minutes": runtime_delay_estimate.minutes,
                "runtime_delay_seconds": runtime_delay_estimate.seconds,
                "runtime_delay_source": runtime_delay_estimate.source,
                "runtime_delay_reason": runtime_delay_estimate.reason,
                "runtime_liveboard_context_present": liveboard_context is not None,
                "runtime_liveboard_fallback_reason": liveboard_fallback_reason,
                "runtime_projection_reason": runtime_projection_reason,
                "runtime_selected_liveboard_station_id": runtime_selected_liveboard.get("StationID") if runtime_selected_liveboard else None,
                "runtime_selected_liveboard_station_name": ((runtime_selected_liveboard.get("StationName") or {}).get("Zh_tw") if runtime_selected_liveboard else None),
                "runtime_selected_liveboard_update_time": runtime_selected_liveboard.get("UpdateTime") if runtime_selected_liveboard else None,
                "benchmark_predicted_eta": benchmark_timing.eta.isoformat(),
                "benchmark_delay_minutes": benchmark_delay_minutes,
                "benchmark_delay_seconds": benchmark_delay_seconds,
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
                "rule_error_seconds": runtime_error_seconds,
                "calibration_eligible": bool(observation.get("calibration_eligible", True)),
            }
        )

    readiness = build_calibration_readiness(rows)
    rules = build_rules(rows)
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    runtime_errors = [abs(int(row["runtime_error_seconds"])) for row in ok_rows]
    benchmark_rows = [row for row in ok_rows if row.get("benchmark_error_seconds") is not None]
    benchmark_errors = [abs(int(row["benchmark_error_seconds"])) for row in benchmark_rows]
    replay_dates = sorted({row.get("service_date") for row in ok_rows if row.get("service_date")})
    return {
        "metadata": {
            "generated_from": str(settings.manual_passage_observations_path.relative_to(ROOT_DIR)),
            "generated_on": date.today().isoformat(),
            "mode": "archived_snapshot_replay",
            "replayed_service_dates": replay_dates,
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
        "readiness": readiness,
        "rules": rules,
        "observations": rows,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Replay archived prediction observations without overwriting the main calibration artifact.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT_DIR / ".runtime" / "prediction" / "prediction_observation_replay.json",
        help="Path to write the replay artifact.",
    )
    args = parser.parse_args()

    payload = await build_replay_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")
    print(json.dumps(payload["baseline"], ensure_ascii=False, indent=2))
    print(json.dumps({"family_ready_count": payload["readiness"]["family_ready_count"], "segment_ready_count": payload["readiness"]["segment_ready_count"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())