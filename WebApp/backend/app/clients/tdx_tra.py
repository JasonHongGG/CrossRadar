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

    def is_valid(self) -> bool:
        return datetime.now(UTC) < self.expires_at


class TdxTraClient:
    def __init__(self, token_manager: TdxTokenManager, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.token_manager = token_manager
        self._cache: dict[str, CacheEntry] = {}

    async def get_stations(self, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        return await self._get_collection(
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
        cache_key = f"timetables:{date.today().isoformat()}"
        return await self._get_collection(
            cache_key=cache_key,
            path="/v3/Rail/TRA/DailyTrainTimetable/Today",
            collection_key="TrainTimetables",
            ttl_seconds=60 * 30,
            force_refresh=force_refresh,
            allow_stale_on_429=True,
            cache_path=self.settings.timetable_cache_path,
            timeout_seconds=10.0,
        )

    async def get_liveboards(self, station_id: str | None = None) -> list[dict[str, Any]]:
        cache_key = f"liveboards:{station_id or 'all'}"
        params = {"$format": "JSON"}
        if station_id:
            params["$filter"] = f"StationID eq '{station_id}'"
        return await self._get_collection(
            cache_key=cache_key,
            path="/v3/Rail/TRA/TrainLiveBoard",
            collection_key="TrainLiveBoards",
            params=params,
            ttl_seconds=45,
            allow_stale_on_429=True,
            empty_on_429=True,
            timeout_seconds=5.0,
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
        cache_entry = self._cache.get(cache_key)
        if not force_refresh and cache_entry and cache_entry.is_valid():
            return cache_entry.value
        if not force_refresh and cache_path and cache_path.exists():
            cached_value = self._read_cache_file(cache_path)
            if cached_value is not None:
                self._cache[cache_key] = CacheEntry(
                    value=cached_value,
                    expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
                )
                return cached_value

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
        collection = payload.get(collection_key, [])
        self._cache[cache_key] = CacheEntry(
            value=collection,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        if cache_path:
            cache_path.write_text(
                json.dumps(
                    {
                        "cached_at": datetime.now(UTC).isoformat(),
                        "data": collection,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        return collection

    def _read_cache_file(self, path: Path) -> list[dict[str, Any]] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        data = payload.get("data")
        if isinstance(data, list):
            return data
        return None

    def _fallback_collection(
        self,
        *,
        cache_entry: CacheEntry | None,
        cache_path: Path | None,
        allow_stale: bool,
        empty_on_failure: bool,
    ) -> list[dict[str, Any]] | None:
        if allow_stale and cache_entry:
            return cache_entry.value
        if allow_stale and cache_path and cache_path.exists():
            cached_value = self._read_cache_file(cache_path)
            if cached_value is not None:
                return cached_value
        if empty_on_failure:
            return []
        return None
