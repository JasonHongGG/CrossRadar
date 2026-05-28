from __future__ import annotations

import json
import pickle

import pytest

from backend.app.clients.tdx_tra import TdxTraClient
from backend.app.config import Settings
from backend.app.http import HttpRequestError


class _StubTokenManager:
    async def get_access_token(self, force_refresh: bool = False) -> str:
        return "token"

    def invalidate(self) -> None:
        return None


class _StubResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
async def test_get_liveboards_raises_on_transport_failure_without_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    client = TdxTraClient(_StubTokenManager(), settings=settings)

    async def raise_transport_error(*args, **kwargs):
        raise HttpRequestError("boom")

    monkeypatch.setattr("backend.app.clients.tdx_tra.request_response", raise_transport_error)

    with pytest.raises(HttpRequestError, match="boom"):
        await client.get_liveboards("1230")


@pytest.mark.asyncio
async def test_get_liveboards_uses_station_cache_file_on_transport_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.liveboard_station_cache_dir = tmp_path / "liveboards"
    settings.liveboard_station_cache_dir.mkdir(parents=True, exist_ok=True)
    (settings.liveboard_station_cache_dir / "1230.json").write_text(
        json.dumps(
            {
                "cached_at": "2026-05-28T00:00:00+00:00",
                "data": [{"TrainNo": "3001", "StationID": "1230"}],
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

    liveboards = await client.get_liveboards("1230", force_refresh=True)

    assert liveboards == [{"TrainNo": "3001", "StationID": "1230"}]


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


@pytest.mark.asyncio
async def test_get_today_timetables_prefers_parsed_file_cache(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.timetable_cache_path = tmp_path / "today_timetables.json"
    serialized_payload = {
        "cached_at": "2026-05-28T00:00:00+00:00",
        "data": [{"TrainInfo": {"TrainNo": "3001"}}],
    }
    settings.timetable_cache_path.write_text(
        json.dumps(serialized_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (tmp_path / "today_timetables.json.pickle").open("wb") as handle:
        pickle.dump(serialized_payload, handle, protocol=pickle.HIGHEST_PROTOCOL)

    client = TdxTraClient(_StubTokenManager(), settings=settings)

    result = await client.get_today_timetables_snapshot()

    assert result.value == [{"TrainInfo": {"TrainNo": "3001"}}]
    assert result.fetched_from == "parsed_file_cache"
    assert result.timing_breakdown == {"parsed_file_cache_read": result.timing_breakdown["parsed_file_cache_read"]}


@pytest.mark.asyncio
async def test_get_today_train_infos_supports_v2_list_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    client = TdxTraClient(_StubTokenManager(), settings=settings)

    async def return_v2_list(*args, **kwargs):
        return _StubResponse([
            {"TrainNo": "3001", "DelayTime": 6},
        ])

    monkeypatch.setattr("backend.app.clients.tdx_tra.request_response", return_v2_list)

    train_infos = await client.get_today_train_infos(force_refresh=True)

    assert train_infos == [{"TrainNo": "3001", "DelayTime": 6}]


@pytest.mark.asyncio
async def test_get_today_train_infos_uses_cache_file_on_transport_failure(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.train_info_cache_path = tmp_path / "today_train_info.json"
    settings.train_info_cache_path.write_text(
        json.dumps(
            {
                "cached_at": "2026-05-28T00:00:00+00:00",
                "data": [{"TrainNo": "3001", "DelayTime": 9}],
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

    train_infos = await client.get_today_train_infos(force_refresh=True)

    assert train_infos == [{"TrainNo": "3001", "DelayTime": 9}]