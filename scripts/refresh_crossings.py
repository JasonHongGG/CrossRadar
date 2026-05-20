from __future__ import annotations

import anyio

from backend.app.dependencies import get_crossing_catalog_service


async def main() -> None:
    catalog = get_crossing_catalog_service()
    dataset = await catalog.refresh(force_refresh=True)
    print(f"Official crossings + OSM curated dataset refreshed: {dataset['metadata']}")


if __name__ == "__main__":
    anyio.run(main)
