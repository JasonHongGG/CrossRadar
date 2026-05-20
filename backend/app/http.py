from __future__ import annotations

from typing import Any

import httpx

from backend.app.config import Settings, get_settings


class HttpRequestError(RuntimeError):
    pass


def _is_ssl_failure(exc: Exception) -> bool:
    message = str(exc).lower()
    return "certificate verify failed" in message or "ssl" in message


async def request_text(
    method: str,
    url: str,
    *,
    settings: Settings | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    data: Any | None = None,
    timeout: float | None = None,
) -> str:
    response = await request_response(
        method,
        url,
        settings=settings,
        headers=headers,
        params=params,
        data=data,
        timeout=timeout,
    )
    return response.text


async def request_json(
    method: str,
    url: str,
    *,
    settings: Settings | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    data: Any | None = None,
    timeout: float | None = None,
) -> Any:
    response = await request_response(
        method,
        url,
        settings=settings,
        headers=headers,
        params=params,
        data=data,
        timeout=timeout,
    )
    return response.json()


async def request_response(
    method: str,
    url: str,
    *,
    settings: Settings | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    data: Any | None = None,
    timeout: float | None = None,
) -> httpx.Response:
    settings = settings or get_settings()
    merged_headers = {
        "User-Agent": settings.http_user_agent,
        **(headers or {}),
    }
    verify_modes: list[bool | str] = [True]
    if settings.allow_insecure_ssl_fallback:
        verify_modes.append(False)

    last_exc: Exception | None = None
    for verify in verify_modes:
        try:
            async with httpx.AsyncClient(
                timeout=timeout or settings.request_timeout_seconds,
                follow_redirects=True,
                verify=verify,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=merged_headers,
                    params=params,
                    data=data,
                )
            return response
        except httpx.TransportError as exc:
            last_exc = exc
            if verify is False or not settings.allow_insecure_ssl_fallback or not _is_ssl_failure(exc):
                break

    raise HttpRequestError(f"HTTP request failed for {url}: {last_exc}")
