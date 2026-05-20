from __future__ import annotations

from backend.app.services.crossing_scraper import TraOfficialCrossingScraper


SAMPLE_HTML = """
<html>
  <body>
    <table>
      <thead>
        <tr>
          <th>平交道名稱</th>
          <th>路線別</th>
          <th>公里標</th>
          <th>道路種類</th>
          <th>站間區間</th>
          <th>縣市</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>德興路(舊名德盛街)</td>
          <td>縱貫線北段</td>
          <td>K089+243</td>
          <td>鄉道</td>
          <td>北湖-湖口</td>
          <td>新竹縣</td>
        </tr>
      </tbody>
    </table>
    <div class="pagination">
      <a href="?activePage=1">1</a>
      <a href="?activePage=5">最末頁</a>
    </div>
  </body>
</html>
"""


def test_parse_page_extracts_crossing_fields() -> None:
    scraper = TraOfficialCrossingScraper()
    records, total_pages = scraper.parse_page(SAMPLE_HTML, 1)
    assert total_pages == 5
    assert len(records) == 1
    record = records[0]
    assert record.name.startswith("德興路")
    assert record.km_value_meters == 89243
    assert record.station_a_name == "北湖"
    assert record.station_b_name == "湖口"
