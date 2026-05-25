from __future__ import annotations

import json

from backend.app.config import Settings
from backend.app.models.crossing import CrossingRecord
from backend.app.services.crossing_scraper import TraOfficialCrossingScraper


class _PartialScraper(TraOfficialCrossingScraper):
    async def fetch_page(self, page_number: int) -> str:
        return f"page-{page_number}"

    def parse_page(self, html: str, page_number: int):
        record = CrossingRecord(
            crossing_id="partial",
            name="部分資料",
            normalized_name="部分資料",
            line="縱貫線",
            km_marker="K001+000",
            km_prefix="",
            km_value_meters=1000,
            road_type="道路",
            station_pair_text="甲站-乙站",
            station_a_name="甲站",
            station_b_name="乙站",
            county="測試縣",
            source_page=page_number,
            source_row_index=1,
        )
        return ([record], 1)


def test_scraper_keeps_cached_dataset_when_refresh_is_suspiciously_small(tmp_path) -> None:
    settings = Settings(TDX_CLIENT_ID="id", TDX_CLIENT_SECRET="secret")
    settings.official_crossings_json_path = tmp_path / "crossings_official.json"
    cached_crossings = []
    for index in range(60):
        cached_crossings.append(
            CrossingRecord(
                crossing_id=f"cached-{index}",
                name=f"樣本{index}",
                normalized_name=f"樣本{index}",
                line="縱貫線",
                km_marker=f"K{index:03d}+000",
                km_prefix="",
                km_value_meters=index * 1000,
                road_type="道路",
                station_pair_text="甲站-乙站",
                station_a_name="甲站",
                station_b_name="乙站",
                county="測試縣",
                source_page=1,
                source_row_index=index + 1,
            )
        )
    settings.official_crossings_json_path.write_text(
        json.dumps(
            {
                "metadata": {"source": "cache", "pages": 1, "count": len(cached_crossings)},
                "crossings": [record.model_dump() for record in cached_crossings],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    scraper = _PartialScraper(settings)
    records = __import__("asyncio").run(scraper.scrape_all(force_refresh=True))

    assert len(records) == len(cached_crossings)
    payload = json.loads(settings.official_crossings_json_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["count"] == len(cached_crossings)