from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.models.crossing import ConfidenceLevel
from backend.app.models.prediction import PredictionEnvelope, PredictionRecord
from backend.app.services.crossing_catalog import CrossingCatalogService
from backend.app.services.station_graph import StationGraphService
from backend.app.utils import now_taipei, parse_time_on_date, safe_int


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
        horizon_minutes: int = 20,
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
        now = now_taipei()
        predictions: list[PredictionRecord] = []

        station_a_id = properties.get("station_a_id")
        station_b_id = properties.get("station_b_id")
        if station_a_id and station_b_id:
            liveboards_a, liveboards_b, timetables = await self._load_segment_data(station_a_id, station_b_id)
            predictions.extend(
                self._build_predictions_from_liveboards(
                    properties,
                    liveboards_a + liveboards_b,
                    timetables,
                    now=now,
                    horizon_minutes=horizon_minutes,
                    warning_minutes=warning_minutes,
                )
            )

            if not predictions:
                predictions.extend(
                    self._build_predictions_from_timetables(
                        properties,
                        timetables,
                        now=now,
                        horizon_minutes=horizon_minutes,
                        warning_minutes=warning_minutes,
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

        return PredictionEnvelope(
            crossing_id=crossing_id,
            generated_at=now,
            warning_window_minutes=warning_minutes,
            horizon_minutes=horizon_minutes,
            predictions=deduped,
        )

    async def _load_segment_data(
        self,
        station_a_id: str,
        station_b_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        liveboards_a = await self.tdx_client.get_liveboards(station_a_id)
        liveboards_b = await self.tdx_client.get_liveboards(station_b_id)
        timetables = await self.tdx_client.get_today_timetables()
        return (liveboards_a, liveboards_b, timetables)

    def _build_predictions_from_liveboards(
        self,
        crossing: dict[str, Any],
        liveboards: list[dict[str, Any]],
        timetables: list[dict[str, Any]],
        *,
        now,
        horizon_minutes: int,
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
            )
            if timetable is None:
                continue

            stop_pair = self._resolve_stop_pair(
                timetable,
                crossing.get("station_a_id"),
                crossing.get("station_b_id"),
            )
            if stop_pair is None:
                continue

            upstream, downstream, direction = stop_pair
            upstream_departure = parse_time_on_date(train_date, upstream.get("DepartureTime") or upstream.get("ArrivalTime"))
            downstream_arrival = parse_time_on_date(train_date, downstream.get("ArrivalTime") or downstream.get("DepartureTime"))
            if upstream_departure is None or downstream_arrival is None or downstream_arrival <= upstream_departure:
                continue

            delay_minutes = safe_int(liveboard.get("DelayTime"), default=0)
            actual_upstream = upstream_departure + timedelta(minutes=delay_minutes)
            actual_downstream = downstream_arrival + timedelta(minutes=delay_minutes)
            ratio = float(crossing.get("segment_ratio") or 0.5)
            eta = actual_upstream + (actual_downstream - actual_upstream) * ratio
            if eta < now - timedelta(minutes=2) or eta > now + timedelta(minutes=horizon_minutes):
                continue

            prediction = PredictionRecord(
                train_no=train_no,
                train_type=self._extract_train_type((timetable.get("TrainInfo", {}) or {}).get("TrainTypeName") or liveboard.get("TrainTypeName")),
                direction=direction,
                source_station_id=liveboard.get("StationID"),
                source_station_name=(liveboard.get("StationName") or {}).get("Zh_tw"),
                upstream_station_id=upstream.get("StationID"),
                upstream_station_name=(upstream.get("StationName") or {}).get("Zh_tw", ""),
                downstream_station_id=downstream.get("StationID"),
                downstream_station_name=(downstream.get("StationName") or {}).get("Zh_tw", ""),
                eta=eta,
                warning=eta <= now + timedelta(minutes=warning_minutes),
                warning_window_minutes=warning_minutes,
                confidence=self._prediction_confidence(crossing.get("geolocation_confidence"), has_liveboard=True),
                delay_minutes=delay_minutes,
                data_basis="liveboard",
                reason=(
                    f"Used TrainLiveBoard from {((liveboard.get('StationName') or {}).get('Zh_tw') or liveboard.get('StationID') or 'unknown station')} "
                    f"with timetable segment {((upstream.get('StationName') or {}).get('Zh_tw') or upstream.get('StationID'))} -> "
                    f"{((downstream.get('StationName') or {}).get('Zh_tw') or downstream.get('StationID'))}."
                ),
                segment_ratio=ratio,
            )
            predictions.append(prediction)

        return predictions

    def _build_predictions_from_timetables(
        self,
        crossing: dict[str, Any],
        timetables: list[dict[str, Any]],
        *,
        now,
        horizon_minutes: int,
        warning_minutes: int,
    ) -> list[PredictionRecord]:
        predictions: list[PredictionRecord] = []
        train_date = date.today()
        for timetable in timetables:
            stop_pair = self._resolve_stop_pair(
                timetable,
                crossing.get("station_a_id"),
                crossing.get("station_b_id"),
            )
            if stop_pair is None:
                continue
            upstream, downstream, direction = stop_pair
            upstream_departure = parse_time_on_date(train_date, upstream.get("DepartureTime") or upstream.get("ArrivalTime"))
            downstream_arrival = parse_time_on_date(train_date, downstream.get("ArrivalTime") or downstream.get("DepartureTime"))
            if upstream_departure is None or downstream_arrival is None or downstream_arrival <= upstream_departure:
                continue

            ratio = float(crossing.get("segment_ratio") or 0.5)
            eta = upstream_departure + (downstream_arrival - upstream_departure) * ratio
            if eta < now or eta > now + timedelta(minutes=horizon_minutes):
                continue

            train_info = timetable.get("TrainInfo", {})
            predictions.append(
                PredictionRecord(
                    train_no=str(train_info.get("TrainNo") or ""),
                    train_type=self._extract_train_type(train_info.get("TrainTypeName")),
                    direction=direction,
                    source_station_id=upstream.get("StationID"),
                    source_station_name=(upstream.get("StationName") or {}).get("Zh_tw"),
                    upstream_station_id=upstream.get("StationID"),
                    upstream_station_name=(upstream.get("StationName") or {}).get("Zh_tw", ""),
                    downstream_station_id=downstream.get("StationID"),
                    downstream_station_name=(downstream.get("StationName") or {}).get("Zh_tw", ""),
                    eta=eta,
                    warning=eta <= now + timedelta(minutes=warning_minutes),
                    warning_window_minutes=warning_minutes,
                    confidence=self._prediction_confidence(crossing.get("geolocation_confidence"), has_liveboard=False),
                    delay_minutes=0,
                    data_basis="timetable",
                    reason="Fallback timetable-only estimation because no nearby liveboard evidence was available.",
                    segment_ratio=ratio,
                )
            )
        return predictions[:10]

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
    ) -> dict[str, Any] | None:
        for timetable in timetables:
            if self._resolve_stop_pair(timetable, station_a_id, station_b_id) is not None:
                return timetable
        return None

    def _resolve_stop_pair(
        self,
        timetable: dict[str, Any],
        station_a_id: str | None,
        station_b_id: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any], int] | None:
        if not station_a_id or not station_b_id:
            return None
        stop_times = timetable.get("StopTimes", [])
        stop_a = next((item for item in stop_times if item.get("StationID") == station_a_id), None)
        stop_b = next((item for item in stop_times if item.get("StationID") == station_b_id), None)
        if stop_a is None or stop_b is None:
            return None
        seq_a = safe_int(stop_a.get("StopSequence"), default=0)
        seq_b = safe_int(stop_b.get("StopSequence"), default=0)
        if seq_a == seq_b:
            return None
        if seq_a < seq_b:
            return (stop_a, stop_b, 0)
        return (stop_b, stop_a, 1)

    def _prediction_confidence(self, geo_confidence: str | None, *, has_liveboard: bool) -> ConfidenceLevel:
        if geo_confidence == "high" and has_liveboard:
            return "high"
        if geo_confidence in ("high", "medium"):
            return "medium"
        return "low"

    def _extract_train_type(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("Zh_tw") or value.get("En")
        return str(value)
