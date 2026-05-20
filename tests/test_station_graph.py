from __future__ import annotations

import asyncio

from backend.app.services.station_graph import StationGraphService


class _StubTdxClient:
    async def get_stations(self) -> list[dict]:
        return [
            {
                "StationID": "7130",
                "StationName": {"Zh_tw": "蘇澳新"},
                "StationPosition": {"PositionLon": 121.84289, "PositionLat": 24.60856},
            },
            {
                "StationID": "1240",
                "StationName": {"Zh_tw": "中洲"},
                "StationPosition": {"PositionLon": 120.51656, "PositionLat": 22.52742},
            },
        ]


def test_resolve_station_supports_alias_and_suffix_fallback() -> None:
    service = StationGraphService(_StubTdxClient())

    station_a = asyncio.run(service.resolve_station("蘇澳新站"))
    station_b = asyncio.run(service.resolve_station("中州"))

    assert station_a is not None
    assert station_a["StationName"]["Zh_tw"] == "蘇澳新"
    assert station_b is not None
    assert station_b["StationName"]["Zh_tw"] == "中洲"