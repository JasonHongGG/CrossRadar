from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from backend.app.config import Settings, get_settings
from backend.app.http import request_text
from backend.app.models.crossing import CrossingRecord
from backend.app.utils import normalize_text, parse_km_marker, slugify_crossing, split_station_pair


class TraOfficialCrossingScraper:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def scrape_all(self, *, force_refresh: bool = False) -> list[CrossingRecord]:
        if not force_refresh and self.settings.official_crossings_json_path.exists():
            return self.load_cached()

        cached_records = self.load_cached() if self.settings.official_crossings_json_path.exists() else []

        page_number = 1
        total_pages: int | None = None
        records: list[CrossingRecord] = []

        while True:
            html = await self.fetch_page(page_number)
            self._write_raw_html(page_number, html)
            page_records, discovered_total_pages = self.parse_page(html, page_number)
            if total_pages is None:
                total_pages = discovered_total_pages or 1
            if not page_records:
                break
            records.extend(page_records)
            if total_pages is not None and page_number >= total_pages:
                break
            page_number += 1

        if cached_records and len(records) < max(50, int(len(cached_records) * 0.9)):
            return cached_records

        payload = {
            "metadata": {
                "source": str(self.settings.tra_crossings_url),
                "pages": page_number,
                "count": len(records),
            },
            "crossings": [record.model_dump() for record in records],
        }
        self.settings.official_crossings_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return records

    def load_cached(self) -> list[CrossingRecord]:
        payload = json.loads(self.settings.official_crossings_json_path.read_text(encoding="utf-8"))
        return [CrossingRecord.model_validate(item) for item in payload.get("crossings", [])]

    async def fetch_page(self, page_number: int) -> str:
        return await request_text(
            "GET",
            self.settings.tra_crossings_url,
            settings=self.settings,
            params={"activePage": str(page_number)},
        )

    def parse_page(self, html: str, page_number: int) -> tuple[list[CrossingRecord], int | None]:
        soup = BeautifulSoup(html, "html.parser")
        table = self._find_target_table(soup)
        if table is None:
            return ([], None)

        body = table.find("tbody")
        rows = body.find_all("tr") if body else table.find_all("tr")
        records: list[CrossingRecord] = []
        for index, row in enumerate(rows, start=1):
            columns = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
            if len(columns) < 6:
                continue
            station_a_name, station_b_name = split_station_pair(columns[4])
            km_parts = parse_km_marker(columns[2])
            record = CrossingRecord(
                crossing_id=slugify_crossing(columns[0], columns[1], columns[2]),
                name=columns[0],
                normalized_name=normalize_text(columns[0]),
                line=columns[1],
                km_marker=columns[2],
                km_prefix=km_parts["km_prefix"],
                km_value_meters=km_parts["km_value_meters"],
                road_type=columns[3],
                query_station_pair_text=columns[4],
                query_station_a_name=station_a_name,
                query_station_b_name=station_b_name,
                station_pair_text=columns[4],
                station_a_name=station_a_name,
                station_b_name=station_b_name,
                county=columns[5],
                source_page=page_number,
                source_row_index=index,
            )
            records.append(record)

        total_pages = self._parse_total_pages(soup)
        return (records, total_pages)

    def _find_target_table(self, soup: BeautifulSoup):
        for table in soup.find_all("table"):
            header_text = " ".join(th.get_text(" ", strip=True) for th in table.find_all("th"))
            if "平交道名稱" in header_text and "路線別" in header_text:
                return table
        return soup.find("table")

    def _parse_total_pages(self, soup: BeautifulSoup) -> int | None:
        page_numbers: set[int] = set()
        for anchor in soup.select("a[href*='activePage=']"):
            href = anchor.get("href", "")
            query = parse_qs(urlparse(href).query)
            values = query.get("activePage", [])
            for value in values:
                if value.isdigit():
                    page_numbers.add(int(value))
        return max(page_numbers) if page_numbers else None

    def _write_raw_html(self, page_number: int, html: str) -> None:
        target = Path(self.settings.crossings_raw_html_dir) / f"page_{page_number:03d}.html"
        target.write_text(html, encoding="utf-8")
