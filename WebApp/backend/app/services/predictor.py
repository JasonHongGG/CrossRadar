from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from time import perf_counter
from typing import Any, Awaitable

from backend.app.clients.tdx_tra import CollectionFetchResult, TdxTraClient
from backend.app.models.crossing import ConfidenceLevel
from backend.app.models.prediction import PredictionDataSnapshot, PredictionEnvelope, PredictionRecord, PredictionSnapshotSource
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.station_graph import StationGraphService
from backend.app.utils import now_taipei, parse_time_on_date, safe_int


@dataclass(slots=True)
class SegmentDataSnapshot:
    liveboards: list[dict[str, Any]]
    timetables: list[dict[str, Any]]
    train_infos: list[dict[str, Any]]
    data_snapshot: PredictionDataSnapshot
    unavailable_reason: str | None = None
    unavailable_detail: str | None = None


class PredictorService:
    def __init__(
        self,
        tdx_client: TdxTraClient,
        catalog_service: CrossingCatalogService,
        station_graph_service: StationGraphService,
    ) -> None:
        self.tdx_client = tdx_client
        self.catalog_service = catalog_service
        self.station_graph_service = station_graph_service

    async def predict_for_crossing(
        self,
        crossing_id: str,
        *,
        horizon_minutes: int | None = None,
        recent_minutes: int = 10,
        warning_minutes: int = 5,
        force_refresh: bool = False,
    ) -> PredictionEnvelope:
        prediction_started = perf_counter()
        feature = await self.catalog_service.get_crossing(crossing_id)
        if feature is None:
            raise KeyError(f"Unknown crossing: {crossing_id}")

        properties = dict(feature.get("properties", {}))
        if feature.get("geometry") is not None:
            coordinates = feature["geometry"].get("coordinates") or [None, None]
            if coordinates[0] is not None and coordinates[1] is not None:
                properties["geometry"] = {"lon": coordinates[0], "lat": coordinates[1]}
        enrich_started = perf_counter()
        properties = await self.station_graph_service.enrich_crossing_properties(properties)
        enrich_ms = self._elapsed_ms(enrich_started)
        crossing = self._build_crossing_feature(crossing_id, feature, properties)

        station_lookup_started = perf_counter()
        station_lookup_by_id = await self.station_graph_service.get_station_lookup_by_id()
        station_lookup_ms = self._elapsed_ms(station_lookup_started)
        now = now_taipei()
        predictions: list[PredictionRecord] = []
        base_timings = {
            "crossing_enrich": enrich_ms,
            "station_lookup": station_lookup_ms,
        }

        station_a_id = properties.get("station_a_id")
        station_b_id = properties.get("station_b_id")
        if not station_a_id or not station_b_id:
            return self._build_unavailable_envelope(
                crossing_id,
                now=now,
                warning_minutes=warning_minutes,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
                reason="station_pair_unresolved",
                detail="The crossing anchor stations could not be resolved from the current station dataset.",
                crossing=crossing,
            )
        if properties.get("segment_ratio") is None or properties.get("ratio_source") != "osm_path":
            return self._build_unavailable_envelope(
                crossing_id,
                now=now,
                warning_minutes=warning_minutes,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
                reason="runtime_segment_unavailable",
                detail=properties.get("segment_confidence_reason") or "This crossing has no accepted OSM runtime segment yet.",
                crossing=crossing,
            )

        segment_data = await self._load_segment_data(
            station_a_id,
            station_b_id,
            force_refresh=force_refresh,
        )
        segment_data.data_snapshot.timings_ms.update(base_timings)
        if segment_data.unavailable_reason:
            segment_data.data_snapshot.timings_ms["total"] = self._elapsed_ms(prediction_started)
            return self._build_unavailable_envelope(
                crossing_id,
                now=now,
                warning_minutes=warning_minutes,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
                reason=segment_data.unavailable_reason,
                detail=segment_data.unavailable_detail or "The prediction snapshot could not be refreshed completely.",
                data_snapshot=segment_data.data_snapshot,
                crossing=crossing,
            )

        train_info_by_train_no = self._build_train_info_index(segment_data.train_infos)

        if station_a_id and station_b_id:
            live_started = perf_counter()
            live_predictions = self._build_predictions_from_liveboards(
                properties,
                segment_data.liveboards,
                segment_data.timetables,
                train_info_by_train_no=train_info_by_train_no,
                station_lookup_by_id=station_lookup_by_id,
                now=now,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
                warning_minutes=warning_minutes,
            )
            segment_data.data_snapshot.timings_ms["live_prediction_build"] = self._elapsed_ms(live_started)

            timetable_started = perf_counter()
            timetable_predictions = self._build_predictions_from_timetables(
                properties,
                segment_data.timetables,
                train_info_by_train_no=train_info_by_train_no,
                station_lookup_by_id=station_lookup_by_id,
                now=now,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
                warning_minutes=warning_minutes,
            )
            segment_data.data_snapshot.timings_ms["timetable_prediction_build"] = self._elapsed_ms(timetable_started)

            merge_started = perf_counter()
            predictions.extend(
                self._dedupe_predictions(
                    self._merge_predictions(
                        live_predictions,
                        timetable_predictions,
                    )
                )
            )
            segment_data.data_snapshot.timings_ms["prediction_merge"] = self._elapsed_ms(merge_started)

        recent_prediction, upcoming_predictions, all_upcoming_predictions = self._partition_predictions(
            predictions,
            now=now,
            recent_minutes=recent_minutes,
        )

        segment_data.data_snapshot.timings_ms["total"] = self._elapsed_ms(prediction_started)

        return PredictionEnvelope(
            crossing_id=crossing_id,
            generated_at=now,
            warning_window_minutes=warning_minutes,
            horizon_minutes=horizon_minutes,
            recent_window_minutes=recent_minutes,
            crossing=crossing,
            available=True,
            data_snapshot=segment_data.data_snapshot,
            recent_prediction=recent_prediction,
            upcoming_predictions=upcoming_predictions,
            predictions=all_upcoming_predictions,
        )

    async def _load_segment_data(
        self,
        station_a_id: str,
        station_b_id: str,
        *,
        force_refresh: bool = False,
    ) -> SegmentDataSnapshot:
        station_scope = list(dict.fromkeys([station_a_id, station_b_id]))
        timed_results = await asyncio.gather(
            *(self._await_with_timing(
                f"liveboards:{station_id}",
                self.tdx_client.get_liveboards_snapshot(station_id, force_refresh=force_refresh),
            ) for station_id in station_scope),
            self._await_with_timing(
                "timetables",
                self.tdx_client.get_today_timetables_snapshot(force_refresh=force_refresh),
            ),
            self._await_with_timing(
                "train_info",
                self.tdx_client.get_today_train_infos_snapshot(force_refresh=force_refresh),
            ),
        )

        timings_ms: dict[str, int] = {}
        liveboard_fetches: list[tuple[str, CollectionFetchResult]] = []
        failed_sources: list[str] = []
        timetables_result: CollectionFetchResult | None = None
        train_info_result: CollectionFetchResult | None = None
        liveboards: list[dict[str, Any]] = []

        for name, elapsed_ms, result, exc in timed_results:
            timings_ms[name] = elapsed_ms
            if name.startswith("liveboards:"):
                station_id = name.split(":", 1)[1]
                if exc is not None or not isinstance(result, CollectionFetchResult):
                    failed_sources.append(f"liveboards[{station_id}]: {exc}")
                    continue
                liveboard_fetches.append((station_id, result))
                liveboards.extend(result.value)
                continue
            if name == "timetables":
                if exc is not None or not isinstance(result, CollectionFetchResult):
                    failed_sources.append(f"today_timetables: {exc}")
                else:
                    timetables_result = result
                continue
            if name == "train_info":
                if exc is not None or not isinstance(result, CollectionFetchResult):
                    failed_sources.append(f"today_train_info: {exc}")
                else:
                    train_info_result = result

        liveboards = self._dedupe_liveboards(liveboards)
        timetables = timetables_result.value if timetables_result is not None else []
        train_infos = train_info_result.value if train_info_result is not None else []

        liveboard_source = PredictionSnapshotSource(
            source="liveboards",
            complete=len(liveboard_fetches) == len(station_scope),
            record_count=len(liveboards),
            delayed_record_count=sum(1 for record in liveboards if safe_int(record.get("DelayTime"), default=0) != 0),
            fetched_from=", ".join(f"{station_id}:{snapshot.fetched_from}" for station_id, snapshot in liveboard_fetches) or None,
            cached_at=max((snapshot.cached_at for _, snapshot in liveboard_fetches if snapshot.cached_at is not None), default=None),
            scope=", ".join(station_scope),
            detail=" | ".join(item for item in failed_sources if item.startswith("liveboards[")) or None,
        )
        timetable_source = PredictionSnapshotSource(
            source="timetables",
            complete=timetables_result is not None,
            record_count=len(timetables),
            fetched_from=timetables_result.fetched_from if timetables_result is not None else None,
            cached_at=timetables_result.cached_at if timetables_result is not None else None,
            detail=next((item for item in failed_sources if item.startswith("today_timetables:")), None),
        )
        train_info_source = PredictionSnapshotSource(
            source="train_info",
            complete=train_info_result is not None,
            record_count=len(train_infos),
            delayed_record_count=sum(1 for record in train_infos if safe_int(record.get("DelayTime"), default=0) != 0),
            fetched_from=train_info_result.fetched_from if train_info_result is not None else None,
            cached_at=train_info_result.cached_at if train_info_result is not None else None,
            detail=next((item for item in failed_sources if item.startswith("today_train_info:")), None),
        )

        data_snapshot = PredictionDataSnapshot(
            comprehensive=liveboard_source.complete and timetable_source.complete and train_info_source.complete,
            liveboard_count=len(liveboards),
            delayed_liveboard_count=liveboard_source.delayed_record_count,
            timetable_count=len(timetables),
            train_info_count=len(train_infos),
            delayed_train_info_count=train_info_source.delayed_record_count,
            liveboard_scope=station_scope,
            sources=[liveboard_source, timetable_source, train_info_source],
            timings_ms=timings_ms,
        )
        if failed_sources:
            return SegmentDataSnapshot(
                liveboards=liveboards,
                timetables=timetables,
                train_infos=train_infos,
                data_snapshot=data_snapshot,
                unavailable_reason="snapshot_incomplete",
                unavailable_detail="Failed to refresh a complete prediction snapshot. " + " | ".join(failed_sources),
            )
        return SegmentDataSnapshot(
            liveboards=liveboards,
            timetables=timetables,
            train_infos=train_infos,
            data_snapshot=data_snapshot,
        )

    async def _await_with_timing(
        self,
        name: str,
        operation: Awaitable[Any],
    ) -> tuple[str, int, Any | None, Exception | None]:
        started = perf_counter()
        try:
            return (name, self._elapsed_ms(started), await operation, None)
        except Exception as exc:
            return (name, self._elapsed_ms(started), None, exc)

    def _build_predictions_from_liveboards(
        self,
        crossing: dict[str, Any],
        liveboards: list[dict[str, Any]],
        timetables: list[dict[str, Any]],
        *,
        train_info_by_train_no: dict[str, dict[str, Any]] | None = None,
        station_lookup_by_id: dict[str, dict[str, Any]],
        now,
        horizon_minutes: int | None,
        recent_minutes: int,
        warning_minutes: int,
    ) -> list[PredictionRecord]:
        predictions: list[PredictionRecord] = []
        timetable_index = self._build_timetable_index(timetables)
        train_date = date.today()

        for liveboard in self._dedupe_liveboards(liveboards):
            train_no = str(liveboard.get("TrainNo") or "")
            if not train_no or train_no not in timetable_index:
                continue
            timetable = self._select_best_timetable(
                timetable_index[train_no],
                crossing.get("station_a_id"),
                crossing.get("station_b_id"),
                station_lookup_by_id=station_lookup_by_id,
            )
            if timetable is None:
                continue

            stop_pair = self._resolve_stop_pair(
                timetable,
                crossing.get("station_a_id"),
                crossing.get("station_b_id"),
                station_lookup_by_id=station_lookup_by_id,
            )
            if stop_pair is None:
                continue

            upstream, downstream, direction = stop_pair
            train_info = timetable.get("TrainInfo", {})
            origin_station_id, origin_station_name, destination_station_id, destination_station_name = self._extract_terminal_stations(timetable)
            upstream_departure = parse_time_on_date(train_date, upstream.get("DepartureTime") or upstream.get("ArrivalTime"))
            downstream_arrival = parse_time_on_date(train_date, downstream.get("ArrivalTime") or downstream.get("DepartureTime"))
            if upstream_departure is None or downstream_arrival is None or downstream_arrival <= upstream_departure:
                continue

            delay_minutes, delay_source = self._resolve_delay_minutes(
                train_no,
                liveboard=liveboard,
                train_info_by_train_no=train_info_by_train_no,
            )
            actual_upstream = upstream_departure + timedelta(minutes=delay_minutes)
            actual_downstream = downstream_arrival + timedelta(minutes=delay_minutes)
            ratio, prediction_ratio_source, prediction_segment_confidence, prediction_segment_note = self._prediction_segment_context(
                crossing,
                upstream_station_id=upstream.get("StationID"),
                downstream_station_id=downstream.get("StationID"),
                station_lookup_by_id=station_lookup_by_id,
            )
            if not self._is_prediction_segment_valid(
                crossing,
                upstream_station_id=upstream.get("StationID"),
                downstream_station_id=downstream.get("StationID"),
                ratio=ratio,
                ratio_source=prediction_ratio_source,
            ):
                continue
            eta = actual_upstream + (actual_downstream - actual_upstream) * ratio
            if not self._is_prediction_in_window(
                eta,
                now=now,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
            ):
                continue

            prediction = PredictionRecord(
                train_no=train_no,
                train_type=self._extract_train_type(train_info.get("TrainTypeName") or liveboard.get("TrainTypeName")),
                direction=direction,
                headsign=self._extract_string(train_info.get("TripHeadSign")),
                origin_station_id=origin_station_id,
                origin_station_name=origin_station_name,
                destination_station_id=destination_station_id,
                destination_station_name=destination_station_name,
                source_station_id=liveboard.get("StationID"),
                source_station_name=(liveboard.get("StationName") or {}).get("Zh_tw"),
                previous_stop_station_id=upstream.get("StationID"),
                previous_stop_station_name=(upstream.get("StationName") or {}).get("Zh_tw", ""),
                previous_stop_departure=actual_upstream,
                next_stop_station_id=downstream.get("StationID"),
                next_stop_station_name=(downstream.get("StationName") or {}).get("Zh_tw", ""),
                next_stop_arrival=actual_downstream,
                upstream_station_id=upstream.get("StationID"),
                upstream_station_name=(upstream.get("StationName") or {}).get("Zh_tw", ""),
                downstream_station_id=downstream.get("StationID"),
                downstream_station_name=(downstream.get("StationName") or {}).get("Zh_tw", ""),
                eta=eta,
                warning=eta <= now + timedelta(minutes=warning_minutes),
                warning_window_minutes=warning_minutes,
                confidence=self._prediction_confidence_with_segment(
                    crossing.get("geolocation_confidence"),
                    prediction_segment_confidence,
                    has_liveboard=True,
                ),
                confidence_reason=self._prediction_confidence_reason(
                    crossing,
                    has_liveboard=True,
                    ratio_source=prediction_ratio_source,
                    segment_note=prediction_segment_note,
                ),
                delay_minutes=delay_minutes,
                delay_source=delay_source,
                data_basis="liveboard",
                prediction_method="liveboard+delay+timetable_segment" if delay_source == "train_info" else "liveboard+timetable_segment",
                reason=(
                    f"Used TrainLiveBoard from {((liveboard.get('StationName') or {}).get('Zh_tw') or liveboard.get('StationID') or 'unknown station')} "
                    f"with timetable segment {((upstream.get('StationName') or {}).get('Zh_tw') or upstream.get('StationID'))} -> "
                    f"{((downstream.get('StationName') or {}).get('Zh_tw') or downstream.get('StationID'))} and {delay_source} delay data."
                ),
                station_pair_source=crossing.get("station_pair_source"),
                ratio_source=prediction_ratio_source,
                segment_confidence=prediction_segment_confidence,
                segment_ratio=ratio,
            )
            predictions.append(prediction)

        return predictions

    def _build_predictions_from_timetables(
        self,
        crossing: dict[str, Any],
        timetables: list[dict[str, Any]],
        *,
        train_info_by_train_no: dict[str, dict[str, Any]] | None = None,
        station_lookup_by_id: dict[str, dict[str, Any]],
        now,
        horizon_minutes: int | None,
        recent_minutes: int,
        warning_minutes: int,
    ) -> list[PredictionRecord]:
        predictions: list[PredictionRecord] = []
        train_date = date.today()
        for timetable in timetables:
            stop_pair = self._resolve_stop_pair(
                timetable,
                crossing.get("station_a_id"),
                crossing.get("station_b_id"),
                station_lookup_by_id=station_lookup_by_id,
            )
            if stop_pair is None:
                continue
            upstream, downstream, direction = stop_pair
            train_info = timetable.get("TrainInfo", {})
            origin_station_id, origin_station_name, destination_station_id, destination_station_name = self._extract_terminal_stations(timetable)
            upstream_departure = parse_time_on_date(train_date, upstream.get("DepartureTime") or upstream.get("ArrivalTime"))
            downstream_arrival = parse_time_on_date(train_date, downstream.get("ArrivalTime") or downstream.get("DepartureTime"))
            if upstream_departure is None or downstream_arrival is None or downstream_arrival <= upstream_departure:
                continue

            train_no = str(train_info.get("TrainNo") or "")
            delay_minutes, delay_source = self._resolve_delay_minutes(
                train_no,
                train_info_by_train_no=train_info_by_train_no,
            )
            actual_upstream = upstream_departure + timedelta(minutes=delay_minutes)
            actual_downstream = downstream_arrival + timedelta(minutes=delay_minutes)

            ratio, prediction_ratio_source, prediction_segment_confidence, prediction_segment_note = self._prediction_segment_context(
                crossing,
                upstream_station_id=upstream.get("StationID"),
                downstream_station_id=downstream.get("StationID"),
                station_lookup_by_id=station_lookup_by_id,
            )
            if not self._is_prediction_segment_valid(
                crossing,
                upstream_station_id=upstream.get("StationID"),
                downstream_station_id=downstream.get("StationID"),
                ratio=ratio,
                ratio_source=prediction_ratio_source,
            ):
                continue
            eta = actual_upstream + (actual_downstream - actual_upstream) * ratio
            if not self._is_prediction_in_window(
                eta,
                now=now,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
            ):
                continue

            predictions.append(
                PredictionRecord(
                    train_no=train_no,
                    train_type=self._extract_train_type(train_info.get("TrainTypeName")),
                    direction=direction,
                    headsign=self._extract_string(train_info.get("TripHeadSign")),
                    origin_station_id=origin_station_id,
                    origin_station_name=origin_station_name,
                    destination_station_id=destination_station_id,
                    destination_station_name=destination_station_name,
                    source_station_id=upstream.get("StationID"),
                    source_station_name=(upstream.get("StationName") or {}).get("Zh_tw"),
                    previous_stop_station_id=upstream.get("StationID"),
                    previous_stop_station_name=(upstream.get("StationName") or {}).get("Zh_tw", ""),
                    previous_stop_departure=actual_upstream,
                    next_stop_station_id=downstream.get("StationID"),
                    next_stop_station_name=(downstream.get("StationName") or {}).get("Zh_tw", ""),
                    next_stop_arrival=actual_downstream,
                    upstream_station_id=upstream.get("StationID"),
                    upstream_station_name=(upstream.get("StationName") or {}).get("Zh_tw", ""),
                    downstream_station_id=downstream.get("StationID"),
                    downstream_station_name=(downstream.get("StationName") or {}).get("Zh_tw", ""),
                    eta=eta,
                    warning=eta <= now + timedelta(minutes=warning_minutes),
                    warning_window_minutes=warning_minutes,
                    confidence=self._prediction_confidence_with_segment(
                        crossing.get("geolocation_confidence"),
                        prediction_segment_confidence,
                        has_liveboard=False,
                    ),
                    confidence_reason=self._prediction_confidence_reason(
                        crossing,
                        has_liveboard=False,
                        ratio_source=prediction_ratio_source,
                        segment_note=prediction_segment_note,
                    ),
                    delay_minutes=delay_minutes,
                    delay_source=delay_source,
                    data_basis="timetable",
                    prediction_method="timetable+delay_segment" if delay_source == "train_info" else "timetable_only",
                    reason=(
                        "Used timetable interpolation with train-info delay data."
                        if delay_source == "train_info"
                        else "Fallback timetable-only estimation because no nearby liveboard evidence was available."
                    ),
                    station_pair_source=crossing.get("station_pair_source"),
                    ratio_source=prediction_ratio_source,
                    segment_confidence=prediction_segment_confidence,
                    segment_ratio=ratio,
                )
            )
        predictions.sort(key=lambda item: item.eta)
        return predictions

    def _is_prediction_in_window(
        self,
        eta,
        *,
        now,
        horizon_minutes: int | None,
        recent_minutes: int,
    ) -> bool:
        if eta < now - timedelta(minutes=recent_minutes):
            return False
        if horizon_minutes is None:
            return True
        return eta <= now + timedelta(minutes=horizon_minutes)

    def _partition_predictions(
        self,
        predictions: list[PredictionRecord],
        *,
        now,
        recent_minutes: int,
        upcoming_limit: int = 2,
    ) -> tuple[PredictionRecord | None, list[PredictionRecord], list[PredictionRecord]]:
        recent_cutoff = now - timedelta(minutes=recent_minutes)
        recent_prediction: PredictionRecord | None = None
        all_upcoming_predictions: list[PredictionRecord] = []

        for prediction in predictions:
            if prediction.eta >= now:
                all_upcoming_predictions.append(prediction)
                continue
            if prediction.eta >= recent_cutoff:
                recent_prediction = prediction

        return (recent_prediction, all_upcoming_predictions[:upcoming_limit], all_upcoming_predictions)

    def _build_timetable_index(self, timetables: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        index: dict[str, list[dict[str, Any]]] = {}
        for timetable in timetables:
            train_info = timetable.get("TrainInfo", {})
            train_no = str(train_info.get("TrainNo") or "")
            if not train_no:
                continue
            index.setdefault(train_no, []).append(timetable)
        return index

    def _select_best_timetable(
        self,
        timetables: list[dict[str, Any]],
        station_a_id: str | None,
        station_b_id: str | None,
        *,
        station_lookup_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        best_timetable: dict[str, Any] | None = None
        best_score: tuple[int, int, int] | None = None
        for timetable in timetables:
            stop_pair = self._resolve_stop_pair(
                timetable,
                station_a_id,
                station_b_id,
                station_lookup_by_id=station_lookup_by_id,
            )
            if stop_pair is None:
                continue
            score = self._timetable_candidate_score(stop_pair, station_a_id, station_b_id)
            if best_score is None or score > best_score:
                best_timetable = timetable
                best_score = score
        return best_timetable

    def _timetable_candidate_score(
        self,
        stop_pair: tuple[dict[str, Any], dict[str, Any], int],
        station_a_id: str | None,
        station_b_id: str | None,
    ) -> tuple[int, int, int]:
        upstream, downstream, _ = stop_pair
        anchor_ids = {station_a_id, station_b_id}
        pair_ids = {upstream.get("StationID"), downstream.get("StationID")}
        exact_match = int(pair_ids == anchor_ids)
        anchor_matches = int(upstream.get("StationID") in anchor_ids) + int(downstream.get("StationID") in anchor_ids)
        seq_gap = abs(safe_int(downstream.get("StopSequence"), default=0) - safe_int(upstream.get("StopSequence"), default=0))
        return (exact_match, anchor_matches, -seq_gap)

    def _resolve_stop_pair(
        self,
        timetable: dict[str, Any],
        station_a_id: str | None,
        station_b_id: str | None,
        *,
        station_lookup_by_id: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any], int] | None:
        if not station_a_id or not station_b_id:
            return None
        stop_times = timetable.get("StopTimes", [])
        if len(stop_times) < 2:
            return None
        stop_a = next((item for item in stop_times if item.get("StationID") == station_a_id), None)
        stop_b = next((item for item in stop_times if item.get("StationID") == station_b_id), None)
        if stop_a is None or stop_b is None:
            if stop_a is not None:
                return self._resolve_single_anchor_stop_pair(
                    stop_times,
                    anchor_stop=stop_a,
                    anchor_station_id=station_a_id,
                    target_station_id=station_b_id,
                    station_lookup_by_id=station_lookup_by_id,
                    anchor_role="a",
                )
            if stop_b is not None:
                return self._resolve_single_anchor_stop_pair(
                    stop_times,
                    anchor_stop=stop_b,
                    anchor_station_id=station_b_id,
                    target_station_id=station_a_id,
                    station_lookup_by_id=station_lookup_by_id,
                    anchor_role="b",
                )
            return None
        seq_a = safe_int(stop_a.get("StopSequence"), default=0)
        seq_b = safe_int(stop_b.get("StopSequence"), default=0)
        if seq_a == seq_b:
            return None
        if seq_a < seq_b:
            return (stop_a, stop_b, 0)
        return (stop_b, stop_a, 1)

    def _resolve_single_anchor_stop_pair(
        self,
        stop_times: list[dict[str, Any]],
        *,
        anchor_stop: dict[str, Any],
        anchor_station_id: str,
        target_station_id: str,
        station_lookup_by_id: dict[str, dict[str, Any]],
        anchor_role: str,
    ) -> tuple[dict[str, Any], dict[str, Any], int] | None:
        try:
            anchor_index = stop_times.index(anchor_stop)
        except ValueError:
            return None

        candidate_indexes = [
            index
            for index in (anchor_index - 1, anchor_index + 1)
            if 0 <= index < len(stop_times)
        ]
        if not candidate_indexes:
            return None

        best_index = self._pick_neighbor_toward_target(
            stop_times,
            anchor_station_id=anchor_station_id,
            target_station_id=target_station_id,
            candidate_indexes=candidate_indexes,
            station_lookup_by_id=station_lookup_by_id,
        )
        if best_index is None:
            return None

        candidate_stop = stop_times[best_index]
        if best_index < anchor_index:
            upstream = candidate_stop
            downstream = anchor_stop
            direction = 0 if anchor_role == "b" else 1
        else:
            upstream = anchor_stop
            downstream = candidate_stop
            direction = 0 if anchor_role == "a" else 1
        return (upstream, downstream, direction)

    def _pick_neighbor_toward_target(
        self,
        stop_times: list[dict[str, Any]],
        *,
        anchor_station_id: str,
        target_station_id: str,
        candidate_indexes: list[int],
        station_lookup_by_id: dict[str, dict[str, Any]],
    ) -> int | None:
        target_position = self._station_position(target_station_id, station_lookup_by_id)
        anchor_position = self._station_position(anchor_station_id, station_lookup_by_id)
        scored_candidates: list[tuple[int, float, float, int]] = []
        used_position_scoring = False
        anchor_distance_to_target = None

        if anchor_position is not None and target_position is not None:
            anchor_distance_to_target = self._position_distance_sq(anchor_position, target_position)

        for index in candidate_indexes:
            candidate_station_id = str(stop_times[index].get("StationID") or "")
            if not candidate_station_id:
                continue
            candidate_position = self._station_position(candidate_station_id, station_lookup_by_id)
            if anchor_position is None or target_position is None or candidate_position is None or anchor_distance_to_target is None:
                continue
            used_position_scoring = True
            candidate_distance = self._position_distance_sq(candidate_position, target_position)
            progress = anchor_distance_to_target - candidate_distance
            alignment = self._position_alignment(anchor_position, target_position, candidate_position)
            if alignment <= 0:
                continue
            scored_candidates.append((0 if progress > 0 else 1, candidate_distance, -alignment, index))

        if scored_candidates:
            scored_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
            return scored_candidates[0][3]

        if used_position_scoring:
            return None

        if len(candidate_indexes) == 1:
            return candidate_indexes[0]
        return None

    def _is_prediction_segment_valid(
        self,
        crossing: dict[str, Any],
        *,
        upstream_station_id: str | None,
        downstream_station_id: str | None,
        ratio: float,
        ratio_source: str | None,
    ) -> bool:
        station_a_id = crossing.get("station_a_id")
        station_b_id = crossing.get("station_b_id")
        if (
            upstream_station_id == station_a_id and downstream_station_id == station_b_id
        ) or (
            upstream_station_id == station_b_id and downstream_station_id == station_a_id
        ):
            return True

        if ratio_source != "osm_path":
            return False
        return 0.0 < ratio < 1.0

    def _station_position(
        self,
        station_id: str | None,
        station_lookup_by_id: dict[str, dict[str, Any]],
    ) -> tuple[float, float] | None:
        if not station_id:
            return None
        station = station_lookup_by_id.get(str(station_id)) or {}
        position = station.get("StationPosition") or {}
        lat = position.get("PositionLat")
        lon = position.get("PositionLon")
        if lat is None or lon is None:
            return None
        return (float(lat), float(lon))

    def _position_distance_sq(self, point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
        return ((point_a[0] - point_b[0]) ** 2) + ((point_a[1] - point_b[1]) ** 2)

    def _position_alignment(
        self,
        anchor_point: tuple[float, float],
        target_point: tuple[float, float],
        candidate_point: tuple[float, float],
    ) -> float:
        target_vector = (target_point[0] - anchor_point[0], target_point[1] - anchor_point[1])
        candidate_vector = (candidate_point[0] - anchor_point[0], candidate_point[1] - anchor_point[1])
        return (target_vector[0] * candidate_vector[0]) + (target_vector[1] * candidate_vector[1])

    def _merge_predictions(
        self,
        live_predictions: list[PredictionRecord],
        timetable_predictions: list[PredictionRecord],
    ) -> list[PredictionRecord]:
        live_train_keys = {(record.train_no, record.upstream_station_id, record.downstream_station_id) for record in live_predictions}
        merged = list(live_predictions)
        merged.extend(
            record
            for record in timetable_predictions
            if (record.train_no, record.upstream_station_id, record.downstream_station_id) not in live_train_keys
        )
        return merged

    def _dedupe_predictions(self, predictions: list[PredictionRecord]) -> list[PredictionRecord]:
        selected: dict[tuple[str, str, str], PredictionRecord] = {}
        for prediction in predictions:
            key = self._prediction_identity_key(prediction)
            current = selected.get(key)
            if current is None or self._prediction_preference_key(prediction) < self._prediction_preference_key(current):
                selected[key] = prediction
        return sorted(
            selected.values(),
            key=lambda item: (item.eta, 0 if item.data_basis == "liveboard" else 1, item.train_no),
        )

    def _prediction_identity_key(self, prediction: PredictionRecord) -> tuple[str, str, str]:
        return (
            prediction.train_no,
            prediction.upstream_station_id,
            prediction.downstream_station_id,
        )

    def _prediction_preference_key(self, prediction: PredictionRecord) -> tuple[int, int, int, Any]:
        basis_rank = 0 if prediction.data_basis == "liveboard" else 1
        source_match_rank = 0 if prediction.source_station_id in {prediction.upstream_station_id, prediction.downstream_station_id} else 1
        delay_rank = 0 if prediction.delay_source == "train_info" else 1 if prediction.delay_source == "liveboard" else 2
        return (basis_rank, source_match_rank, delay_rank, prediction.eta)

    def _dedupe_liveboards(self, liveboards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str, int]] = set()
        for liveboard in liveboards:
            train_no = str(liveboard.get("TrainNo") or "").strip()
            if not train_no:
                continue
            key = self._liveboard_identity_key(liveboard)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(liveboard)
        return deduped

    def _liveboard_identity_key(self, liveboard: dict[str, Any]) -> tuple[str, str, str, int]:
        return (
            str(liveboard.get("TrainNo") or "").strip(),
            str(liveboard.get("StationID") or "").strip(),
            str(liveboard.get("UpdateTime") or liveboard.get("SrcUpdateTime") or "").strip(),
            safe_int(liveboard.get("DelayTime"), default=0),
        )

    def _build_train_info_index(self, train_infos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for train_info in train_infos:
            train_no = str(train_info.get("TrainNo") or "").strip()
            if not train_no:
                continue
            index[train_no] = train_info
        return index

    def _resolve_delay_minutes(
        self,
        train_no: str,
        *,
        liveboard: dict[str, Any] | None = None,
        train_info_by_train_no: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[int, str]:
        if train_no and train_info_by_train_no:
            train_info = train_info_by_train_no.get(train_no)
            if train_info is not None and train_info.get("DelayTime") is not None:
                return (safe_int(train_info.get("DelayTime"), default=0), "train_info")
        if liveboard is not None and liveboard.get("DelayTime") is not None:
            return (safe_int(liveboard.get("DelayTime"), default=0), "liveboard")
        return (0, "none")

    def _prediction_confidence(self, geo_confidence: str | None, *, has_liveboard: bool) -> ConfidenceLevel:
        return self._prediction_confidence_with_segment(
            geo_confidence,
            None,
            has_liveboard=has_liveboard,
        )

    def _prediction_confidence_with_segment(
        self,
        geo_confidence: str | None,
        segment_confidence: str | None,
        *,
        has_liveboard: bool,
    ) -> ConfidenceLevel:
        base_rank = min(self._confidence_rank(geo_confidence), self._confidence_rank(segment_confidence or geo_confidence))
        if base_rank >= 3 and has_liveboard:
            return "high"
        if base_rank >= 2:
            return "medium"
        return "low"

    def _confidence_rank(self, value: str | None) -> int:
        if value == "high":
            return 3
        if value == "medium":
            return 2
        return 1

    def _prediction_confidence_reason(
        self,
        crossing: dict[str, Any],
        *,
        has_liveboard: bool,
        ratio_source: str | None = None,
        segment_note: str | None = None,
    ) -> str:
        timing_basis = "liveboard + timetable segment" if has_liveboard else "timetable fallback"
        ratio_source = ratio_source or crossing.get("ratio_source") or "unknown"
        pair_source = crossing.get("station_pair_source") or "official_query"
        segment_note = segment_note or crossing.get("segment_confidence_reason") or "No segment-confidence note was available."
        return f"Timing source: {timing_basis}. Pair source: {pair_source}. Ratio source: {ratio_source}. {segment_note}"

    def _prediction_segment_context(
        self,
        crossing: dict[str, Any],
        *,
        upstream_station_id: str | None,
        downstream_station_id: str | None,
        station_lookup_by_id: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[float | None, str, ConfidenceLevel, str]:
        raw_ratio = crossing.get("segment_ratio")
        ratio = None if raw_ratio is None else min(max(float(raw_ratio), 0.0), 1.0)
        ratio_source = str(crossing.get("ratio_source") or "unavailable")
        segment_confidence = crossing.get("segment_confidence") or crossing.get("geolocation_confidence") or "low"
        segment_note = crossing.get("segment_confidence_reason") or "No segment-confidence note was available."
        station_a_id = crossing.get("station_a_id")
        station_b_id = crossing.get("station_b_id")

        if ratio is not None and ratio_source == "osm_path" and upstream_station_id == station_a_id and downstream_station_id == station_b_id:
            return (ratio, ratio_source, segment_confidence, segment_note)
        if ratio is not None and ratio_source == "osm_path" and upstream_station_id == station_b_id and downstream_station_id == station_a_id:
            return (1.0 - ratio, ratio_source, segment_confidence, segment_note)

        projected_ratio, projected_source, projected_confidence, projected_note = self._project_ratio_for_stop_pair(
            crossing,
            upstream_station_id=upstream_station_id,
            downstream_station_id=downstream_station_id,
            station_lookup_by_id=station_lookup_by_id,
        )
        if projected_ratio is not None:
            return (projected_ratio, projected_source, projected_confidence, projected_note)

        return (None, projected_source, projected_confidence, projected_note if projected_note else segment_note)

    def _extract_terminal_stations(self, timetable: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
        train_info = timetable.get("TrainInfo", {}) or {}
        stop_times = timetable.get("StopTimes", [])
        first_stop = stop_times[0] if stop_times else {}
        last_stop = stop_times[-1] if stop_times else {}
        origin_station_id = train_info.get("StartingStationID") or first_stop.get("StationID")
        origin_station_name = self._extract_station_name(train_info.get("StartingStationName")) or self._extract_station_name(first_stop.get("StationName"))
        destination_station_id = train_info.get("EndingStationID") or last_stop.get("StationID")
        destination_station_name = self._extract_station_name(train_info.get("EndingStationName")) or self._extract_station_name(last_stop.get("StationName"))
        return (origin_station_id, origin_station_name, destination_station_id, destination_station_name)

    def _estimate_crossing_eta(
        self,
        crossing: dict[str, Any],
        *,
        upstream_station_id: str | None,
        downstream_station_id: str | None,
        upstream_departure,
        downstream_arrival,
        station_lookup_by_id: dict[str, dict[str, Any]] | None = None,
    ):
        ratio, _, _, _ = self._prediction_segment_context(
            crossing,
            upstream_station_id=upstream_station_id,
            downstream_station_id=downstream_station_id,
            station_lookup_by_id=station_lookup_by_id,
        )
        if ratio is None:
            raise ValueError("Cannot estimate a crossing ETA without an OSM runtime segment ratio.")
        return (
            upstream_departure + (downstream_arrival - upstream_departure) * ratio,
            ratio,
        )

    def _project_ratio_for_stop_pair(
        self,
        crossing: dict[str, Any],
        *,
        upstream_station_id: str | None,
        downstream_station_id: str | None,
        station_lookup_by_id: dict[str, dict[str, Any]] | None,
    ) -> tuple[float | None, str, ConfidenceLevel, str]:
        return self.station_graph_service.resolve_runtime_ratio_for_station_pair(
            crossing,
            upstream_station_id=upstream_station_id,
            downstream_station_id=downstream_station_id,
            station_lookup_by_id=station_lookup_by_id,
        )

    def _build_unavailable_envelope(
        self,
        crossing_id: str,
        *,
        now,
        warning_minutes: int,
        horizon_minutes: int | None,
        recent_minutes: int,
        reason: str,
        detail: str,
        data_snapshot: PredictionDataSnapshot | None = None,
        crossing: dict[str, Any] | None = None,
    ) -> PredictionEnvelope:
        return PredictionEnvelope(
            crossing_id=crossing_id,
            generated_at=now,
            warning_window_minutes=warning_minutes,
            horizon_minutes=horizon_minutes,
            recent_window_minutes=recent_minutes,
            crossing=crossing,
            available=False,
            unavailable_reason=reason,
            unavailable_detail=detail,
            data_snapshot=data_snapshot,
        )

    def _build_crossing_feature(
        self,
        crossing_id: str,
        feature: dict[str, Any],
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_properties = dict(properties)
        for key in (
            "official_segment_ratio",
            "geometry_segment_ratio",
            "path_segment_ratio",
            "station_a_route_km_meters",
            "station_b_route_km_meters",
            "station_route_reference_note",
            "station_pair_reference_note",
            "segment_ratio_override",
            "segment_ratio_override_source",
            "segment_ratio_override_confidence",
            "segment_ratio_override_note",
        ):
            runtime_properties.pop(key, None)
        return {
            **feature,
            "id": feature.get("id") or crossing_id,
            "properties": runtime_properties,
        }

    def _elapsed_ms(self, started_at: float) -> int:
        return int((perf_counter() - started_at) * 1000)

    def _extract_train_type(self, value: Any) -> str | None:
        return self._extract_station_name(value)

    def _extract_station_name(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("Zh_tw") or value.get("En")
        return str(value)

    def _extract_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
