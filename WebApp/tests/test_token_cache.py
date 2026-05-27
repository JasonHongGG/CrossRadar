from __future__ import annotations

import httpx
import pytest

from backend.app.clients.tdx_auth import TdxTokenManager
from backend.app.config import Settings


@pytest.mark.asyncio
async def test_token_cache_reuses_token() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"access_token": "token-1", "expires_in": 3600})

    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    transport = httpx.MockTransport(handler)
    manager = TdxTokenManager(settings=settings, transport=transport)

    first = await manager.get_access_token()
    second = await manager.get_access_token()

    assert first == "token-1"
    assert second == "token-1"
    assert call_count == 1
