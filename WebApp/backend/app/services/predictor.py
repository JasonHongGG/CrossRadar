from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.models.crossing import ConfidenceLevel
from backend.app.models.prediction import PredictionEnvelope, PredictionRecord
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.station_graph import StationGraphService
from backend.app.utils import now_taipei, parse_time_on_date, point_ratio_between_stations, safe_int


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
    ) -> PredictionEnvelope:
        feature = await self.catalog_service.get_crossing(crossing_id)
        if feature is None:
            raise KeyError(f"Unknown crossing: {crossing_id}")

        properties = dict(feature.get("properties", {}))
        if feature.get("geometry") is not None:
            coordinates = feature["geometry"].get("coordinates") or [None, None]
            if coordinates[0] is not None and coordinates[1] is not None:
                properties["geometry"] = {"lon": coordinates[0], "lat": coordinates[1]}
        properties = await self.station_graph_service.enrich_crossing_properties(properties)
        station_lookup_by_id = await self.station_graph_service.get_station_lookup_by_id()
        now = now_taipei()
        predictions: list[PredictionRecord] = []

        station_a_id = properties.get("station_a_id")
        station_b_id = properties.get("station_b_id")
        if station_a_id and station_b_id:
            liveboards_a, liveboards_b, timetables = await self._load_segment_data(station_a_id, station_b_id)
            live_predictions = self._build_predictions_from_liveboards(
                properties,
                liveboards_a + liveboards_b,
                timetables,
                station_lookup_by_id=station_lookup_by_id,
                now=now,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
                warning_minutes=warning_minutes,
            )
            timetable_predictions = self._build_predictions_from_timetables(
                properties,
                timetables,
                station_lookup_by_id=station_lookup_by_id,
                now=now,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
                warning_minutes=warning_minutes,
            )
            predictions.extend(
                self._merge_predictions(
                    live_predictions,
                    timetable_predictions,
                )
            )

        predictions.sort(key=lambda item: item.eta)
        deduped: list[PredictionRecord] = []
        seen: set[tuple[str, str]] = set()
        for prediction in predictions:
            key = (prediction.train_no, prediction.source_station_id or prediction.upstream_station_id)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(prediction)

        recent_prediction, upcoming_predictions, all_upcoming_predictions = self._partition_predictions(
            deduped,
            now=now,
            recent_minutes=recent_minutes,
        )

        return PredictionEnvelope(
            crossing_id=crossing_id,
            generated_at=now,
            warning_window_minutes=warning_minutes,
            horizon_minutes=horizon_minutes,
            recent_window_minutes=recent_minutes,
            recent_prediction=recent_prediction,
            upcoming_predictions=upcoming_predictions,
            predictions=all_upcoming_predictions,
        )

    async def _load_segment_data(
        self,
        station_a_id: str,
        station_b_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        liveboards_a_result, liveboards_b_result, timetables_result = await asyncio.gather(
            self.tdx_client.get_liveboards(station_a_id),
            self.tdx_client.get_liveboards(station_b_id),
            self.tdx_client.get_today_timetables(),
            return_exceptions=True,
        )

        liveboards_a = liveboards_a_result if isinstance(liveboards_a_result, list) else []
        liveboards_b = liveboards_b_result if isinstance(liveboards_b_result, list) else []
        timetables = timetables_result if isinstance(timetables_result, list) else []
        return (liveboards_a, liveboards_b, timetables)

    def _build_predictions_from_liveboards(
        self,
        crossing: dict[str, Any],
        liveboards: list[dict[str, Any]],
        timetables: list[dict[str, Any]],
        *,
        station_lookup_by_id: dict[str, dict[str, Any]],
        now,
        horizon_minutes: int | None,
        recent_minutes: int,
        warning_minutes: int,
    ) -> list[PredictionRecord]:
        predictions: list[PredictionRecord] = []
        timetable_index = self._build_timetable_index(timetables)
        train_date = date.today()

        for liveboard in liveboards:
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

            delay_minutes = safe_int(liveboard.get("DelayTime"), default=0)
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
                data_basis="liveboard",
                prediction_method="liveboard+timetable_segment",
                reason=(
                    f"Used TrainLiveBoard from {((liveboard.get('StationName') or {}).get('Zh_tw') or liveboard.get('StationID') or 'unknown station')} "
                    f"with timetable segment {((upstream.get('StationName') or {}).get('Zh_tw') or upstream.get('StationID'))} -> "
                    f"{((downstream.get('StationName') or {}).get('Zh_tw') or downstream.get('StationID'))}."
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
            eta = upstream_departure + (downstream_arrival - upstream_departure) * ratio
            if not self._is_prediction_in_window(
                eta,
                now=now,
                horizon_minutes=horizon_minutes,
                recent_minutes=recent_minutes,
            ):
                continue

            predictions.append(
                PredictionRecord(
                    train_no=str(train_info.get("TrainNo") or ""),
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
                    previous_stop_departure=upstream_departure,
                    next_stop_station_id=downstream.get("StationID"),
                    next_stop_station_name=(downstream.get("StationName") or {}).get("Zh_tw", ""),
                    next_stop_arrival=downstream_arrival,
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
                    delay_minutes=0,
                    data_basis="timetable",
                    prediction_method="timetable_only",
                    reason="Fallback timetable-only estimation because no nearby liveboard evidence was available.",
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
        for timetable in timetables:
            if self._resolve_stop_pair(
                timetable,
                station_a_id,
                station_b_id,
                station_lookup_by_id=station_lookup_by_id,
            ) is not None:
                return timetable
        return None

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
        scored_candidates: list[tuple[float, float, int]] = []
        used_position_scoring = False

        for index in candidate_indexes:
            candidate_station_id = str(stop_times[index].get("StationID") or "")
            if not candidate_station_id:
                continue
            candidate_position = self._station_position(candidate_station_id, station_lookup_by_id)
            if anchor_position is None or target_position is None or candidate_position is None:
                continue
            used_position_scoring = True
            alignment = self._position_alignment(anchor_position, target_position, candidate_position)
            if alignment <= 0:
                continue
            distance = self._position_distance_sq(candidate_position, target_position)
            scored_candidates.append((-alignment, distance, index))

        if scored_candidates:
            scored_candidates.sort(key=lambda item: (item[0], item[1]))
            return scored_candidates[0][2]

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

        if ratio_source != "geometry_projection":
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
    ) -> tuple[float, str, ConfidenceLevel, str]:
        raw_ratio = float(crossing.get("segment_ratio") or 0.5)
        ratio = min(max(raw_ratio, 0.0), 1.0)
        ratio_source = str(crossing.get("ratio_source") or "unknown")
        segment_confidence = crossing.get("segment_confidence") or crossing.get("geolocation_confidence") or "low"
        segment_note = crossing.get("segment_confidence_reason") or "No segment-confidence note was available."
        station_a_id = crossing.get("station_a_id")
        station_b_id = crossing.get("station_b_id")

        if upstream_station_id == station_a_id and downstream_station_id == station_b_id:
            return (ratio, ratio_source, segment_confidence, segment_note)
        if upstream_station_id == station_b_id and downstream_station_id == station_a_id:
            return (1.0 - ratio, ratio_source, segment_confidence, segment_note)

        projected_ratio = self._project_ratio_for_stop_pair(
            crossing,
            upstream_station_id=upstream_station_id,
            downstream_station_id=downstream_station_id,
            station_lookup_by_id=station_lookup_by_id,
        )
        if projected_ratio is not None:
            return (
                projected_ratio,
                "geometry_projection",
                "medium",
                "Projected the crossing onto the train's actual previous/next stop pair because this service skips one of the crossing anchor stations.",
            )

        return (ratio, ratio_source, segment_confidence, segment_note)

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
    ) -> float | None:
        geometry = crossing.get("geometry") or {}
        if not isinstance(geometry, dict):
            return None
        point_lon = geometry.get("lon")
        point_lat = geometry.get("lat")
        if point_lon is None or point_lat is None or not station_lookup_by_id:
            return None

        upstream_position = self._station_position(upstream_station_id, station_lookup_by_id)
        downstream_position = self._station_position(downstream_station_id, station_lookup_by_id)
        if upstream_position is None or downstream_position is None:
            return None

        return point_ratio_between_stations(
            upstream_position[1],
            upstream_position[0],
            downstream_position[1],
            downstream_position[0],
            float(point_lon),
            float(point_lat),
        )

    def _effective_segment_ratio(
        self,
        crossing: dict[str, Any],
        *,
        upstream_station_id: str | None,
        downstream_station_id: str | None,
    ) -> float:
        raw_ratio = float(crossing.get("segment_ratio") or 0.5)
        ratio = min(max(raw_ratio, 0.0), 1.0)
        station_a_id = crossing.get("station_a_id")
        station_b_id = crossing.get("station_b_id")

        if upstream_station_id == station_a_id and downstream_station_id == station_b_id:
            return ratio
        if upstream_station_id == station_b_id and downstream_station_id == station_a_id:
            return 1.0 - ratio
        return ratio

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
