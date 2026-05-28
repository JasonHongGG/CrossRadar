from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import pickle
from time import perf_counter
from typing import Any

import httpx

from backend.app.clients.tdx_auth import TdxTokenManager
from backend.app.config import Settings, get_settings
from backend.app.http import HttpRequestError, request_response


@dataclass(slots=True)
class CacheEntry:
    value: list[dict[str, Any]]
    expires_at: datetime
    cached_at: datetime | None = None

    def is_valid(self) -> bool:
        return datetime.now(UTC) < self.expires_at


@dataclass(slots=True)
class CachePayload:
    value: list[dict[str, Any]]
    cached_at: datetime | None = None


@dataclass(slots=True)
class CacheReadResult:
    payload: CachePayload
    fetched_from: str
    timing_breakdown: dict[str, int]


@dataclass(slots=True)
class CollectionFetchResult:
    value: list[dict[str, Any]]
    fetched_from: str
    cached_at: datetime | None = None
    timing_breakdown: dict[str, int] | None = None


class TdxTraClient:
    def __init__(self, token_manager: TdxTokenManager, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.token_manager = token_manager
        self._cache: dict[str, CacheEntry] = {}

    async def get_stations(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        return (await self.get_stations_snapshot(force_refresh=force_refresh)).value

    async def get_stations_snapshot(self, *, force_refresh: bool = False) -> CollectionFetchResult:
        return await self._get_collection_with_meta(
            cache_key="stations",
            path="/v3/Rail/TRA/Station",
            collection_key="Stations",
            ttl_seconds=60 * 60 * 12,
            force_refresh=force_refresh,
            allow_stale_on_429=True,
            cache_path=self.settings.station_cache_path,
            timeout_seconds=12.0,
        )

    async def get_today_timetables(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        return (await self.get_today_timetables_snapshot(force_refresh=force_refresh)).value

    async def get_today_timetables_snapshot(self, *, force_refresh: bool = False) -> CollectionFetchResult:
        cache_key = f"timetables:{date.today().isoformat()}"
        return await self._get_collection_with_meta(
            cache_key=cache_key,
            path="/v3/Rail/TRA/DailyTrainTimetable/Today",
            collection_key="TrainTimetables",
            ttl_seconds=60 * 30,
            memory_ttl_seconds=60 * 60 * 2,
            force_refresh=force_refresh,
            allow_stale_on_429=True,
            cache_path=self.settings.timetable_cache_path,
            timeout_seconds=10.0,
        )

    async def get_liveboards(self, station_id: str | None = None, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        return (await self.get_liveboards_snapshot(station_id, force_refresh=force_refresh)).value

    async def get_liveboards_snapshot(
        self,
        station_id: str | None = None,
        *,
        force_refresh: bool = False,
    ) -> CollectionFetchResult:
        cache_key = f"liveboards:{station_id or 'all'}"
        params = {"$format": "JSON"}
        if station_id:
            params["$filter"] = f"StationID eq '{station_id}'"
        return await self._get_collection_with_meta(
            cache_key=cache_key,
            path="/v3/Rail/TRA/TrainLiveBoard",
            collection_key="TrainLiveBoards",
            params=params,
            ttl_seconds=90,
            force_refresh=force_refresh,
            allow_stale_on_429=True,
            cache_path=self._liveboard_cache_path(station_id),
            timeout_seconds=5.0,
        )

    async def get_today_train_infos(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        return (await self.get_today_train_infos_snapshot(force_refresh=force_refresh)).value

    async def get_today_train_infos_snapshot(self, *, force_refresh: bool = False) -> CollectionFetchResult:
        cache_key = f"train-info:{date.today().isoformat()}"
        return await self._get_collection_with_meta(
            cache_key=cache_key,
            path="/v2/Rail/TRA/DailyTrainInfo/Today",
            collection_key="TrainInfos",
            ttl_seconds=60 * 5,
            force_refresh=force_refresh,
            allow_stale_on_429=True,
            cache_path=self.settings.train_info_cache_path,
            timeout_seconds=10.0,
        )

    async def _get_collection(
        self,
        *,
        cache_key: str,
        path: str,
        collection_key: str,
        ttl_seconds: int,
        memory_ttl_seconds: int | None = None,
        params: dict[str, Any] | None = None,
        force_refresh: bool = False,
        allow_stale_on_429: bool = False,
        empty_on_429: bool = False,
        cache_path: Path | None = None,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        result = await self._get_collection_with_meta(
            cache_key=cache_key,
            path=path,
            collection_key=collection_key,
            ttl_seconds=ttl_seconds,
            memory_ttl_seconds=memory_ttl_seconds,
            params=params,
            force_refresh=force_refresh,
            allow_stale_on_429=allow_stale_on_429,
            empty_on_429=empty_on_429,
            cache_path=cache_path,
            timeout_seconds=timeout_seconds,
        )
        return result.value

    async def _get_collection_with_meta(
        self,
        *,
        cache_key: str,
        path: str,
        collection_key: str,
        ttl_seconds: int,
        memory_ttl_seconds: int | None = None,
        params: dict[str, Any] | None = None,
        force_refresh: bool = False,
        allow_stale_on_429: bool = False,
        empty_on_429: bool = False,
        cache_path: Path | None = None,
        timeout_seconds: float | None = None,
    ) -> CollectionFetchResult:
        effective_memory_ttl = memory_ttl_seconds or ttl_seconds
        cache_entry = self._cache.get(cache_key)
        if not force_refresh and cache_entry and cache_entry.is_valid():
            return CollectionFetchResult(
                value=cache_entry.value,
                fetched_from="memory_cache",
                cached_at=cache_entry.cached_at,
                timing_breakdown={"memory_cache": 0},
            )
        if not force_refresh and cache_path and cache_path.exists():
            cached_value = self._read_cache_file(cache_path)
            if cached_value is not None:
                self._cache[cache_key] = CacheEntry(
                    value=cached_value.payload.value,
                    expires_at=datetime.now(UTC) + timedelta(seconds=effective_memory_ttl),
                    cached_at=cached_value.payload.cached_at,
                )
                return CollectionFetchResult(
                    value=cached_value.payload.value,
                    fetched_from=cached_value.fetched_from,
                    cached_at=cached_value.payload.cached_at,
                    timing_breakdown=cached_value.timing_breakdown,
                )

        url = f"{self.settings.tdx_basic_base_url}{path}"
        final_params = {"$format": "JSON", **(params or {})}
        token = await self.token_manager.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        try:
            network_started = perf_counter()
            response = await request_response(
                "GET",
                url,
                settings=self.settings,
                headers=headers,
                params=final_params,
                timeout=timeout_seconds,
            )
        except HttpRequestError:
            fallback = self._fallback_collection(
                cache_entry=cache_entry,
                cache_path=cache_path,
                allow_stale=allow_stale_on_429,
                empty_on_failure=empty_on_429,
            )
            if fallback is not None:
                return fallback
            raise

        if response.status_code == 401:
            self.token_manager.invalidate()
            token = await self.token_manager.get_access_token(force_refresh=True)
            headers = {"Authorization": f"Bearer {token}"}
            try:
                network_started = perf_counter()
                response = await request_response(
                    "GET",
                    url,
                    settings=self.settings,
                    headers=headers,
                    params=final_params,
                    timeout=timeout_seconds,
                )
            except HttpRequestError:
                fallback = self._fallback_collection(
                    cache_entry=cache_entry,
                    cache_path=cache_path,
                    allow_stale=allow_stale_on_429,
                    empty_on_failure=empty_on_429,
                )
                if fallback is not None:
                    return fallback
                raise

        if response.status_code == 429:
            fallback = self._fallback_collection(
                cache_entry=cache_entry,
                cache_path=cache_path,
                allow_stale=allow_stale_on_429,
                empty_on_failure=empty_on_429,
            )
            if fallback is not None:
                return fallback
            response.raise_for_status()

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            fallback = self._fallback_collection(
                cache_entry=cache_entry,
                cache_path=cache_path,
                allow_stale=allow_stale_on_429,
                empty_on_failure=empty_on_429,
            )
            if fallback is not None:
                return fallback
            raise

        payload_started = perf_counter()
        payload = response.json()
        network_timings = {
            "network_fetch": self._elapsed_ms(network_started),
            "network_parse": self._elapsed_ms(payload_started),
        }
        collection = self._extract_collection(payload, collection_key)
        cached_at = datetime.now(UTC)
        self._cache[cache_key] = CacheEntry(
            value=collection,
            expires_at=datetime.now(UTC) + timedelta(seconds=effective_memory_ttl),
            cached_at=cached_at,
        )
        if cache_path:
            network_timings.update(self._write_cache_file(cache_path, cached_at, collection))
        return CollectionFetchResult(
            value=collection,
            fetched_from="network",
            cached_at=cached_at,
            timing_breakdown=network_timings,
        )

    def _read_cache_file(self, path: Path) -> CacheReadResult | None:
        parsed_cache_path = self._parsed_cache_path(path)
        if parsed_cache_path.exists():
            parsed_started = perf_counter()
            try:
                with parsed_cache_path.open("rb") as handle:
                    parsed_payload = pickle.load(handle)
            except (OSError, EOFError, pickle.PickleError, AttributeError, TypeError, ValueError):
                parsed_payload = None
            else:
                try:
                    parsed_is_current = parsed_cache_path.stat().st_mtime >= path.stat().st_mtime
                except OSError:
                    parsed_is_current = False
                if parsed_is_current:
                    payload = self._cache_payload_from_serialized(parsed_payload)
                    if payload is not None:
                        return CacheReadResult(
                            payload=payload,
                            fetched_from="parsed_file_cache",
                            timing_breakdown={"parsed_file_cache_read": self._elapsed_ms(parsed_started)},
                        )

        read_started = perf_counter()
        try:
            raw_text = path.read_text(encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            return None
        read_ms = self._elapsed_ms(read_started)
        parse_started = perf_counter()
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return None
        parse_ms = self._elapsed_ms(parse_started)
        cache_payload = self._cache_payload_from_serialized(payload)
        if cache_payload is None:
            return None
        timing_breakdown = {
            "file_cache_read": read_ms,
            "file_cache_parse": parse_ms,
        }
        parsed_cache_write_ms = self._write_parsed_cache(parsed_cache_path, payload)
        if parsed_cache_write_ms is not None:
            timing_breakdown["parsed_cache_write"] = parsed_cache_write_ms
        return CacheReadResult(
            payload=cache_payload,
            fetched_from="file_cache",
            timing_breakdown=timing_breakdown,
        )

    def _extract_collection(self, payload: Any, collection_key: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            collection = payload.get(collection_key, [])
            if isinstance(collection, list):
                return [item for item in collection if isinstance(item, dict)]
        return []

    def _fallback_collection(
        self,
        *,
        cache_entry: CacheEntry | None,
        cache_path: Path | None,
        allow_stale: bool,
        empty_on_failure: bool,
    ) -> CollectionFetchResult | None:
        if allow_stale and cache_entry:
            return CollectionFetchResult(
                value=cache_entry.value,
                fetched_from="stale_memory_cache",
                cached_at=cache_entry.cached_at,
                timing_breakdown={"stale_memory_cache": 0},
            )
        if allow_stale and cache_path and cache_path.exists():
            cached_value = self._read_cache_file(cache_path)
            if cached_value is not None:
                return CollectionFetchResult(
                    value=cached_value.payload.value,
                    fetched_from=f"stale_{cached_value.fetched_from}",
                    cached_at=cached_value.payload.cached_at,
                    timing_breakdown=cached_value.timing_breakdown,
                )
        if empty_on_failure:
            return CollectionFetchResult(value=[], fetched_from="empty_fallback", timing_breakdown={"empty_fallback": 0})
        return None

    def _cache_payload_from_serialized(self, payload: Any) -> CachePayload | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if not isinstance(data, list):
            return None
        cached_at = self._parse_cached_at(payload.get("cached_at"))
        return CachePayload(
            value=[item for item in data if isinstance(item, dict)],
            cached_at=cached_at,
        )

    def _parse_cached_at(self, raw_value: Any) -> datetime | None:
        if not isinstance(raw_value, str):
            return None
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            return None

    def _write_cache_file(self, cache_path: Path, cached_at: datetime, collection: list[dict[str, Any]]) -> dict[str, int]:
        serialized_payload = {
            "cached_at": cached_at.isoformat(),
            "data": collection,
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        write_started = perf_counter()
        cache_path.write_text(
            json.dumps(serialized_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        timing_breakdown = {"cache_write": self._elapsed_ms(write_started)}
        parsed_cache_write_ms = self._write_parsed_cache(self._parsed_cache_path(cache_path), serialized_payload)
        if parsed_cache_write_ms is not None:
            timing_breakdown["parsed_cache_write"] = parsed_cache_write_ms
        return timing_breakdown

    def _write_parsed_cache(self, parsed_cache_path: Path, payload: dict[str, Any]) -> int | None:
        parsed_cache_path.parent.mkdir(parents=True, exist_ok=True)
        write_started = perf_counter()
        try:
            with parsed_cache_path.open("wb") as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError:
            return None
        return self._elapsed_ms(write_started)

    def _parsed_cache_path(self, cache_path: Path) -> Path:
        return cache_path.with_suffix(f"{cache_path.suffix}.pickle")

    def _liveboard_cache_path(self, station_id: str | None) -> Path:
        if station_id is None:
            return self.settings.liveboard_cache_path
        sanitized_station_id = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in station_id)
        return self.settings.liveboard_station_cache_dir / f"{sanitized_station_id}.json"

    def _elapsed_ms(self, started: float) -> int:
        return max(0, round((perf_counter() - started) * 1000))
