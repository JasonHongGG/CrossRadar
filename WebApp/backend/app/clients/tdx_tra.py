from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
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
class CollectionFetchResult:
    value: list[dict[str, Any]]
    fetched_from: str
    cached_at: datetime | None = None


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
            ttl_seconds=45,
            force_refresh=force_refresh,
            allow_stale_on_429=True,
            cache_path=self.settings.liveboard_cache_path if station_id is None else None,
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
        params: dict[str, Any] | None = None,
        force_refresh: bool = False,
        allow_stale_on_429: bool = False,
        empty_on_429: bool = False,
        cache_path: Path | None = None,
        timeout_seconds: float | None = None,
    ) -> CollectionFetchResult:
        cache_entry = self._cache.get(cache_key)
        if not force_refresh and cache_entry and cache_entry.is_valid():
            return CollectionFetchResult(
                value=cache_entry.value,
                fetched_from="memory_cache",
                cached_at=cache_entry.cached_at,
            )
        if not force_refresh and cache_path and cache_path.exists():
            cached_value = self._read_cache_file(cache_path)
            if cached_value is not None:
                self._cache[cache_key] = CacheEntry(
                    value=cached_value.value,
                    expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
                    cached_at=cached_value.cached_at,
                )
                return CollectionFetchResult(
                    value=cached_value.value,
                    fetched_from="file_cache",
                    cached_at=cached_value.cached_at,
                )

        url = f"{self.settings.tdx_basic_base_url}{path}"
        final_params = {"$format": "JSON", **(params or {})}
        token = await self.token_manager.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        try:
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
        payload = response.json()
        collection = self._extract_collection(payload, collection_key)
        cached_at = datetime.now(UTC)
        self._cache[cache_key] = CacheEntry(
            value=collection,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            cached_at=cached_at,
        )
        if cache_path:
            cache_path.write_text(
                json.dumps(
                    {
                        "cached_at": cached_at.isoformat(),
                        "data": collection,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return CollectionFetchResult(
            value=collection,
            fetched_from="network",
            cached_at=cached_at,
        )

    def _read_cache_file(self, path: Path) -> CachePayload | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        data = payload.get("data")
        if isinstance(data, list):
            cached_at_raw = payload.get("cached_at")
            cached_at = None
            if isinstance(cached_at_raw, str):
                try:
                    cached_at = datetime.fromisoformat(cached_at_raw)
                except ValueError:
                    cached_at = None
            return CachePayload(value=data, cached_at=cached_at)
        return None

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
            )
        if allow_stale and cache_path and cache_path.exists():
            cached_value = self._read_cache_file(cache_path)
            if cached_value is not None:
                return CollectionFetchResult(
                    value=cached_value.value,
                    fetched_from="stale_file_cache",
                    cached_at=cached_value.cached_at,
                )
        if empty_on_failure:
            return CollectionFetchResult(value=[], fetched_from="empty_fallback")
        return None
