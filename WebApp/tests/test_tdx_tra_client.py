from __future__ import annotations

import json

import pytest

from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.config import Settings
from backend.app.http import HttpRequestError


class _StubTokenManager:
    async def get_access_token(self, force_refresh: bool = False) -> str:
        return "token"

    def invalidate(self) -> None:
        return None


@pytest.mark.asyncio
async def test_get_liveboards_returns_empty_on_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    client = TdxTraClient(_StubTokenManager(), settings=settings)

    async def raise_transport_error(*args, **kwargs):
        raise HttpRequestError("boom")

    monkeypatch.setattr("backend.app.clients.tdx_tra.request_response", raise_transport_error)

    liveboards = await client.get_liveboards("1230")

    assert liveboards == []


@pytest.mark.asyncio
async def test_get_today_timetables_uses_cache_file_on_transport_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.timetable_cache_path = tmp_path / "today_timetables.json"
    settings.timetable_cache_path.write_text(
        json.dumps(
            {
                "cached_at": "2026-05-28T00:00:00+00:00",
                "data": [{"TrainInfo": {"TrainNo": "3001"}}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    client = TdxTraClient(_StubTokenManager(), settings=settings)

    async def raise_transport_error(*args, **kwargs):
        raise HttpRequestError("boom")

    monkeypatch.setattr("backend.app.clients.tdx_tra.request_response", raise_transport_error)

    timetables = await client.get_today_timetables(force_refresh=True)

    assert timetables == [{"TrainInfo": {"TrainNo": "3001"}}]