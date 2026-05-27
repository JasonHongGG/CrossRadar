只看 crossings_curated.geojson 的 403 筆 runtime 資料後，現在「沒辦法做可用 OSM」的共有 31 筆。其餘不在 curated 的我這次都排除了。

目前分成 4 類：

station_pair_unresolved，共 24 筆
原因：這些 crossing 雖然在 curated 裡有位置，但前後站對在目前資料流裡解不出來，所以根本無法做 OSM along-track ratio。
項目：逢甲路、明燈路、北堤路(一)、北堤路(二)、更生路、南河、山頂路、八德街、5號碼頭、八股頭、光復路、二十份、勝興、調車場入口、溪底路、清泉路、清泉國中、菁埔里、三塊厝、三美路、溪浦(一)、溪浦(二)、高美路、西濱公路。

station_a_cannot_snap_same_component，共 1 筆
原因：站點能解出，但其中一端車站在目前 OSM rail graph 上無法 snap 到同一個有效 component。
項目：中興路(後潭)-縱貫線北段-k303270。

path_exceeds_station_span，共 4 筆
原因：OSM 路徑可以算出來，但沿軌距離明顯長到超出合理站間範圍，所以被判定為不可信，改回 geometry projection。
項目：溪洲、上茄苳、嘉民、青寮路。

path_ratio_conflicts_with_geometry，共 2 筆
原因：OSM 路徑雖然有結果，但和直線幾何投影差太大，而且距離又夠長，因此被判定為不可信。
項目：水上村、大仁路。

另外有 3 筆你可能會在意，但我沒有算進「沒辦法做 OSM」：

大同路141巷：現在已經可以做 OSM path 了，只是靠人工座標補進來，沒有 OSM crossing node。
實踐路：OSM 可用，但 app 最後選官方里程。
東豐路：OSM 可用，但 app 最後選官方里程。
換句話說，現在 curated 的 403 筆裡：

370 筆目前直接採用 osm_path
7 筆有幾何 fallback，因為 OSM 路徑不可信
2 筆有可用 OSM，但最終採用官方里程
24 筆因站對無法解析，連 OSM path 都無法成立
如果你要，我下一步可以直接只針對臺南市 curated 內還不能做 OSM 的那幾筆繼續處理，目前就是：

上茄苳
嘉民
青寮路