from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx

from backend.app.config import Settings, get_settings
from backend.app.http import request_json


@dataclass(slots=True)
class CachedToken:
    access_token: str
    expires_at: datetime

    def is_valid(self, *, skew_seconds: int) -> bool:
        return datetime.now(UTC) + timedelta(seconds=skew_seconds) < self.expires_at


class TdxAuthError(RuntimeError):
    pass


class TdxTokenManager:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings or get_settings()
        self.transport = transport
        self._lock = anyio.Lock()
        self._cached_token: CachedToken | None = None

    async def get_access_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._cached_token and self._cached_token.is_valid(
            skew_seconds=self.settings.tdx_token_refresh_skew_seconds
        ):
            return self._cached_token.access_token

        async with self._lock:
            if not force_refresh and self._cached_token and self._cached_token.is_valid(
                skew_seconds=self.settings.tdx_token_refresh_skew_seconds
            ):
                return self._cached_token.access_token

            self._cached_token = await self._request_new_token()
            return self._cached_token.access_token

    def invalidate(self) -> None:
        self._cached_token = None

    async def _request_new_token(self) -> CachedToken:
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.settings.tdx_client_id,
            "client_secret": self.settings.tdx_client_secret,
        }

        if self.transport is not None:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(self.settings.tdx_token_url, data=payload)

            if response.status_code >= 400:
                raise TdxAuthError(f"TDX auth failed with status {response.status_code}: {response.text}")

            data: dict[str, Any] = response.json()
        else:
            data = await request_json(
                "POST",
                self.settings.tdx_token_url,
                settings=self.settings,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        access_token = data.get("access_token")
        expires_in = int(data.get("expires_in", 0))

        if not access_token or expires_in <= 0:
            raise TdxAuthError("TDX auth response did not include a usable access token")

        return CachedToken(
            access_token=access_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        )
