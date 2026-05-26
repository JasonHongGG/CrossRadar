# CrossRadar Flutter App 系統化實作計畫

本文是把目前 CrossRadar Web prototype 轉成 Flutter 手機 App 的完整實作計畫。App 的核心目標不是重新做一套預測邏輯，而是把已驗證的後端預測能力、平交道資料、地圖選取與倒數體驗，整理成適合手機使用的產品。

## 1. 產品定位

CrossRadar 手機 App 讓使用者選定一個臺鐵平交道後，快速知道：

- 下一班最接近的列車何時通過。
- 第二班列車何時通過。
- 本次開啟 App 之後，剛剛經過的上一班列車是哪一班。
- 每班列車上一個停靠站、離站時間、下一個停靠站與預計到站時間。
- 預測來源可信度與資料基礎，例如即時資料、班表資料、官方鏈公里、OSM 軌道、座標投影。

手機 App 的第一版應該是一個實用的現場工具，而不是介紹頁或行銷頁。第一個畫面就要是可操作的地圖、搜尋與列車倒數。

## 2. 必須保留的既有產品規則

以下規則來自目前 Web 版已修正過的核心行為，Flutter App 必須照做。

1. 預測真相來源在後端
   - Flutter 不重寫 ETA 推估演算法。
   - Flutter 透過 API 取得 crossing catalog、crossing detail、prediction envelope。
   - 後端負責 liveboard + timetable merge、skip-stop stop-pair resolution、actual stop-pair geometry projection。

2. API 呼叫時機要克制
   - App 啟動時可載入平交道清單。
   - 使用者選擇平交道時更新一次 detail + predictions。
   - 使用者點擊刷新時更新一次 predictions。
   - 不要每秒或定時自動打 predictions API。
   - 倒數更新只靠本機 timer，不打 API。

3. 上一班資料是 session-local
   - App 開啟後，`上一班` 初始是空的。
   - 不主動向後端找上一班。
   - 不直接顯示後端 `recent_prediction`。
   - 當目前追蹤中的下一班或第二班跨過 ETA 後，App 才把該 record 更新為 `上一班`。

4. 倒數要以秒級呈現
   - Hero 區顯示：`現在 HH:mm:ss · 預計 HH:mm:ss 通過`。
   - 倒數每秒刷新，但只刷新本機 state。
   - 列表內時間也要能顯示秒，避免 `16:46` 但還在倒數數十秒時造成誤會。

5. 顯示下一班與第二班
   - 主要顯示 slots 固定為三格：`上一班`、`下一班`、`第二班`。
   - `下一班` 與 `第二班` 來自後端 `upcoming_predictions`，不足時才從 `predictions` 內篩選未來 ETA 補上。
   - 第一版 horizon 建議使用 120 分鐘，warning window 使用 5 分鐘。

6. Flutter App 必須呈現資料來源與可信度
   - 至少在 crossing detail 或 debug/metadata section 顯示 ratio source、station pair source、confidence。
   - 使用者不需要每次都看技術細節，但資料不確定時應有低調提示。

## 3. 後端 API 契約

第一版 Flutter App 直接使用目前 FastAPI API。

### 3.1 載入平交道清單

Endpoint:

```text
GET /api/crossings?limit=5000&mapped_only=true
```

用途：

- App 啟動時載入全台可定位平交道。
- 建立搜尋索引。
- 在地圖上建立 marker。
- 建立縣市、車站、平交道三種 search suggestions。

重要欄位：

- `features[].id`
- `features[].geometry.coordinates`
- `features[].properties.name`
- `features[].properties.county`
- `features[].properties.line`
- `features[].properties.km_marker`
- `features[].properties.station_a_name`
- `features[].properties.station_b_name`
- `features[].properties.station_pair_text`
- `features[].properties.ratio_source`
- `features[].properties.station_pair_source`
- `features[].properties.geolocation_confidence`

### 3.2 載入單一平交道 detail

Endpoint:

```text
GET /api/crossings/{crossing_id}
```

用途：

- 使用者選取平交道時取得 enriched properties。
- 顯示前後站位置。
- 顯示資料來源與可信度。
- 地圖上畫出 crossing + station context。

重要欄位：

- `properties.station_a_id`
- `properties.station_b_id`
- `properties.station_a_name`
- `properties.station_b_name`
- `properties.station_a_position`
- `properties.station_b_position`
- `properties.segment_ratio`
- `properties.ratio_source`
- `properties.segment_confidence`
- `properties.segment_confidence_reason`
- `properties.authoritative_reference_applied`
- `properties.manual_mapping_applied`
- `properties.osm_rail_way_ids`

### 3.3 載入預測

Endpoint:

```text
GET /api/predictions/{crossing_id}?horizon_minutes=120&recent_minutes=10&warning_minutes=5
```

用途：

- 使用者選取平交道時載入。
- 使用者手動刷新時載入。
- App 本機倒數不會重新呼叫此 API。

重要 envelope 欄位：

- `crossing_id`
- `generated_at`
- `warning_window_minutes`
- `horizon_minutes`
- `recent_window_minutes`
- `upcoming_predictions`
- `predictions`

Flutter 第一版不要顯示 `recent_prediction` 作為上一班，因為上一班已改為本機 session state。

重要 prediction record 欄位：

- `train_no`
- `train_type`
- `direction`
- `origin_station_name`
- `destination_station_name`
- `previous_stop_station_name`
- `previous_stop_departure`
- `next_stop_station_name`
- `next_stop_arrival`
- `upstream_station_id`
- `upstream_station_name`
- `downstream_station_id`
- `downstream_station_name`
- `eta`
- `warning_window_minutes`
- `confidence`
- `confidence_reason`
- `delay_minutes`
- `data_basis`
- `prediction_method`
- `station_pair_source`
- `ratio_source`
- `segment_confidence`
- `segment_ratio`

## 4. App 導覽結構

第一版建議採用單一主流程，不使用複雜 bottom navigation。手機上的主要互動都在 `Map Home` 內完成。

### 4.1 Page: Map Home

角色：App 第一畫面，也是核心工作台。

內容：

- 全螢幕地圖。
- 上方搜尋列。
- 目前選取平交道 badge。
- 平交道 markers。
- 選取後出現 bottom sheet。
- 右下角或底部浮動定位/重置控制。

主要功能：

- 啟動時載入 crossing catalog。
- 顯示所有已定位平交道 marker。
- 點 marker 選取 crossing。
- 搜尋縣市、車站、平交道。
- 聚焦搜尋結果範圍。
- 選取 crossing 後打 detail + predictions API。

手機排版：

- 地圖 full-screen，不用桌面版三欄 layout。
- Search bar 固定在 safe area top，寬度為螢幕寬度扣除 16dp padding。
- Bottom sheet 有三個 snap sizes：
  - Collapsed: 顯示 crossing 名稱、下一班倒數摘要。
  - Medium: 顯示三個班次 slots。
  - Expanded: 顯示 crossing detail、資料來源、前後站、metadata。
- 地圖 marker 不要被 bottom sheet 完全遮住，選取 marker 時 camera 要留 bottom padding。

### 4.2 Page/Sheet: Search Sheet

角色：讓使用者快速找到地區、車站或平交道。

入口：點擊 Map Home 上方搜尋列。

內容：

- Search text field。
- 最近選取或常用平交道。
- 搜尋 suggestions：縣市、車站、平交道。
- 搜尋結果 list。

主要功能：

- 本機搜尋，不打 API。
- 文字 normalization：trim、lowercase、移除空白、中文間空白壓縮。
- 支援 county exact match。
- 支援 station exact match。
- 支援 crossing name partial match。
- 點選 county/station 時更新地圖範圍與結果。
- 點選 crossing 時選取 crossing 並關閉 sheet。

排版設計：

- Search sheet 從底部或全屏 modal 進入，視螢幕高度決定。
- 搜尋欄固定在 sheet 頂部。
- Suggestion item 高度 56dp 至 68dp，方便拇指點擊。
- 使用 icon + label + secondary text：
  - 縣市：縣市 icon + crossing count。
  - 車站：station icon + count。
  - 平交道：crossing icon + line/km。

### 4.3 Sheet: Crossing Watch Sheet

角色：選取平交道後的主要資訊面板。

內容：

- Crossing summary。
- Alert hero。
- 三個 schedule slots。
- 手動刷新按鈕。
- 狀態列。

主要功能：

- 顯示下一班倒數。
- 顯示秒級現在時間與預計通過時間。
- 顯示上一班、下一班、第二班。
- 點刷新時只重打 predictions API。
- 若 detail 已有 cache，刷新不重打 crossing detail。
- timer 每秒更新 UI，不打 API。

Collapsed 狀態：

- 顯示 crossing 名稱。
- 顯示最重要倒數，例如 `6分12秒`。
- 顯示 train no、direction、預計通過秒級時間。

Medium 狀態：

- 顯示三個 slots。
- 顯示 refresh button。
- 顯示簡短狀態：已更新、載入中、載入失敗。

Expanded 狀態：

- 顯示更多 crossing metadata。
- 顯示資料來源與可信度。
- 顯示前後站定位與 station pair。
- 顯示 prediction debug line，但不要干擾主要閱讀。

### 4.4 Page/Sheet: Crossing Detail

角色：資料透明度與 debug 檢查。

內容：

- 平交道名稱、縣市、路線、公里標。
- 前後站與官方站間文字。
- Station pair source。
- Ratio source。
- Segment confidence。
- Segment confidence reason。
- Manual mapping / authoritative reference badge。
- OSM rail way IDs，第一版可放在可展開區。

功能：

- 讓使用者理解為什麼某些預測是班表或座標估算。
- 開發/驗證階段可快速看資料來源。
- 生產版可以把技術欄位收在 `資料來源` accordion。

### 4.5 Page: Settings / Diagnostics

第一版可以放在 Map Home 的 overflow menu，非主 tab。

內容：

- API base URL。
- Catalog last updated time。
- App version。
- 資料來源說明。
- OSM attribution。
- 清除 local cache。
- Debug mode toggle。

功能：

- 開發測試時切換 localhost、LAN backend、production backend。
- 檢查目前 API 是否可連線。
- 匯出最近一次 prediction envelope，方便 debug。

## 5. UI 元件設計

### 5.1 AppScaffold

職責：

- 管理 safe area。
- 管理 global overlay，例如 loading banner、offline banner。
- 管理 global theme。

設計：

- 背景以地圖為主。
- UI surface 使用低透明度或實色 surface，不要干擾地圖。
- 手機第一版避免桌面式左右欄。

### 5.2 SearchBarControl

元素：

- Search icon。
- Placeholder：`搜尋縣市、車站、平交道`。
- 清除按鈕。
- Filter/suggestion button。

功能：

- Tap 開啟 Search Sheet。
- 已輸入文字時顯示清除按鈕。
- 搜尋本機 catalog，不打 API。

### 5.3 MapView

建議套件：

- `flutter_map` + `latlong2`。
- OSM tile layer。
- 可替換成 Mapbox 或 Google Maps，但第一版建議沿用 OSM，與 Web prototype 一致。

元素：

- Crossing marker。
- Selected crossing marker。
- Station marker。
- Station segment polyline。
- Optional user location marker。
- Attribution overlay。

互動：

- Tap marker: select crossing。
- Map drag: 不自動取消選取。
- Focus button: camera 移動到 selected crossing + station points。
- Search result focus: fit bounds。

Marker 設計：

- 一般 crossing：小圓點，coral accent。
- selected crossing：較大圓點 + 外圈，不用文字標籤覆蓋地圖。
- station：小圓點，station A/B 用不同 accent。
- Marker hit target 至少 44dp，可視圖形可小，gesture area 要大。

### 5.4 CrossingSummaryCard

元素：

- 縣市 badge。
- 名稱。
- 路線 + 公里標。
- 前後站 compact row。
- Confidence badge。

設計：

- Card radius 8dp。
- 高度固定或使用 min-height，避免資料刷新時跳動。
- 中文名稱可換行，但不擠壓主要倒數區。

### 5.5 AlertHeroCard

元素：

- Data basis chip：`即時` / `班表`。
- Train no chip。
- Direction chip。
- 大倒數文字。
- `現在 HH:mm:ss · 預計 HH:mm:ss 通過`。
- Origin -> destination route。
- Previous/next stop mini cards。

狀態：

- Idle：沒有 120 分鐘內列車，顯示 `SAFE`。
- Scheduled：只有班表預測。
- Watch：有即時資料但不在 warning window。
- Alert：在 warning window 內。
- Loading：剛選取 crossing，等待 API。
- Error：prediction API 失敗。

設計：

- 倒數是最大資訊，但不要讓 H1 級字體擠壓其他資訊。
- ETA 一律顯示秒，減少 `同一分鐘但還有秒數` 的誤解。
- Warning 色只用在真正 alert 狀態，不要因為沒有列車就誤用安全綠色造成過度戲劇化。

### 5.6 TrainSlotCard

三種 slot：

- `上一班`：session-local record。
- `下一班`：upcoming[0]。
- `第二班`：upcoming[1]。

元素：

- Slot label。
- Status chip：`已通過` / `即時` / `班表`。
- Train no + train type。
- Origin -> destination。
- Direction。
- Previous stop name + departure time。
- Next stop name + arrival time。
- Countdown pill。
- Pass time HH:mm:ss。

空狀態：

- 上一班：`暫無上一班資料` / `本次開啟後尚未記錄到通過列車`。
- 下一班：`暫無下一班資料` / `120 分鐘內沒有接近平交道的列車`。
- 第二班：`暫無第二班資料`。

穩定排版：

- 每張 card 設定 min-height。
- Stop timing grid 使用兩欄；窄螢幕低於 360dp 時改成上下堆疊。
- Countdown pill 固定寬度，避免每秒數字變化造成 layout shift。

### 5.7 StopTimingPair

元素：

- 左：上一停靠，站名，離站時間。
- 右：下一停靠，站名，到站時間。

設計：

- 站名使用 1 行或 2 行限制。
- 時間使用 tabular figures。
- 若資料缺失，顯示 `未提供`，不要留空。

### 5.8 DataSourceBadges

Badges：

- `官方鏈公里`
- `OSM 軌道路徑`
- `座標估算`
- `中點 fallback`
- `官方校正`
- `官網欄位`
- `人工校正`

用途：

- Crossing summary 顯示 1 至 2 個最重要 badge。
- Detail expanded section 顯示完整資料來源。

### 5.9 RefreshButton

行為：

- 只有 selected crossing 時 enabled。
- Loading 時 disabled 並顯示 spinner。
- 點擊只更新 predictions。
- Detail 已存在時不重打 crossing detail。

文案：

- Button label：`更新`。
- Loading status：`正在更新列車預測...`。
- Success status：`已更新`。
- Error status：`載入預測失敗`。

## 6. 視覺與排版設計

### 6.1 Design tokens

延續 Web 版的安靜工具感，但在手機上降低裝飾性。

建議色彩：

- Background: `#F7F3EC`
- Surface: `#FFFCF7`
- Ink: `#1A3049`
- Muted: `#67768A`
- Navy: `#1F446A`
- Coral: `#FF7B5B`
- Gold: `#FFD36A`
- Sky: `#90D7FF`
- Success: `#0E7F72`
- Caution: `#9B6712`
- Danger: `#BF5137`

Typography：

- 中文：系統字體優先，例如 `Noto Sans TC` 在 Android 可透過 bundled font 或 fallback。
- 英數與 train no：可使用系統 sans；若要延續品牌感可用 `Sora`，但第一版不必強依賴外部字體。
- 倒數與時間使用 tabular figures。

Spacing：

- Page padding: 16dp。
- Sheet internal padding: 16dp。
- Card gap: 10dp 至 12dp。
- Card radius: 8dp。
- Bottom sheet top radius: 20dp，可視為 sheet container 而非 card。
- Touch target: 最小 44dp。

### 6.2 手機 portrait layout

結構：

```text
SafeArea
  Stack
    MapView full screen
    Top SearchBarControl
    Map controls
    DraggableScrollableSheet
      CrossingSummary
      AlertHero
      ScheduleSlots
      Details accordion
```

重點：

- Map 是主要背景，不放在卡片內。
- Bottom sheet 是主要資訊承載。
- 搜尋結果用 sheet，不用桌面 sidebar。
- 不做 landing page。

### 6.3 手機 landscape / tablet layout

結構：

```text
Row
  Expanded MapView
  SizedBox(width: 380-460) WatchPanel
```

行為：

- 大螢幕可固定右側 WatchPanel。
- Search 可以保持 top overlay。
- Map camera padding 依 panel 寬度調整。

### 6.4 Loading / Empty / Error states

Catalog loading：

- 地圖 skeleton + status banner。
- Search disabled。

No selected crossing：

- Bottom sheet collapsed 顯示 `選一個平交道`。

Prediction loading：

- 保留 crossing summary。
- Alert hero 顯示 loading skeleton。
- Schedule slots skeleton。

No trains：

- Hero 顯示 `SAFE`。
- Slots 顯示空狀態文案。

Network error：

- 不清掉既有成功資料。
- 顯示 retry button。
- Status banner 顯示錯誤。

Stale data：

- 顯示 `最後更新 HH:mm:ss`。
- 不自動刷新，但提示使用者可點更新。

## 7. 功能設計

### 7.1 啟動流程

流程：

1. App start。
2. 讀取 local cached crossing catalog。
3. 若 cache 存在，先顯示 cache。
4. 呼叫 `/api/crossings?limit=5000&mapped_only=true` 更新 catalog。
5. 建立 search index。
6. 地圖顯示 markers。

注意：

- Catalog API 可以在啟動時呼叫一次。
- 若 API 失敗且 cache 存在，App 仍可進入離線瀏覽。
- 若 API 失敗且沒有 cache，顯示 retry。

### 7.2 搜尋與篩選

搜尋資料來源：本機 catalog。

Search index 欄位：

- crossing name。
- county。
- line。
- km marker。
- station pair。
- station A。
- station B。

搜尋 types：

- County：聚焦該縣市所有 crossings。
- Station：聚焦 station A/B 包含該站的 crossings。
- Crossing：直接選取該 crossing。

排序：

- 預設由南到北排序，延續現有 Web 行為。
- 搜尋結果可優先 exact match，再 partial match。

### 7.3 選取平交道

流程：

1. 使用者點 marker 或 search result。
2. 設定 selectedCrossingId。
3. 如果 crossing detail cache 不存在，呼叫 detail API。
4. 呼叫 predictions API。
5. 收到 envelope 後建立本機 prediction session。
6. 在地圖上顯示 selected marker + station markers + station segment。
7. Bottom sheet 展示 watch panel。

重要行為：

- 新選取 crossing 時，該 crossing 的 `上一班` slot 初始為空。
- 已存在同 crossing session runtime 時可保留上一班，但 MVP 建議新選取就清空，行為最直觀。
- 若要跨 crossing 保留 session state，需明確在 UX 上說明，第一版不建議。

### 7.4 手動刷新

流程：

1. 使用者點 `更新`。
2. 若 selected crossing 不存在，按鈕 disabled。
3. 呼叫 predictions API。
4. 成功後更新 envelope。
5. 保留 session-local 上一班。
6. 將已經早於 now 的 predictions 標記為 processed，避免刷新後回填舊車。

注意：

- Refresh 不主動打 detail API，除非 detail cache 不存在。
- Refresh 不會清空上一班。
- Refresh 不會自動把後端 recent_prediction 寫入上一班。

### 7.5 倒數與上一班更新

本機 state：

```dart
class PredictionRuntimeState {
  final PredictionEnvelope? envelope;
  final PredictionRecord? lastPassedRecord;
  final Set<String> processedPredictionKeys;
  final DateTime now;
}
```

Prediction key 建議：

```text
train_no | upstream_station_id | downstream_station_id | eta
```

Timer 行為：

- 每秒更新 `now`。
- 每秒檢查 envelope.predictions。
- 找出 `eta <= now` 且 key 不在 processed set 的 records。
- 若有 newly passed，依 ETA 排序，最後一筆更新為 `lastPassedRecord`。
- newly passed keys 加入 processed set。
- UI 重新計算 upcoming。
- 不打 API。

初始載入行為：

- 收到 envelope 時，把 `eta <= now` 的 records 加入 processed set。
- 不把它們塞進 lastPassedRecord。
- 這可保證 App 開啟時上一班是空的。

### 7.6 Upcoming selection

演算法：

1. 從 envelope.upcoming_predictions 篩出 `eta >= now`。
2. 若至少 2 筆，取前兩筆。
3. 若不足，從 envelope.predictions 篩出 `eta >= now` 排序後補足。
4. UI 顯示 `下一班` 與 `第二班`。

### 7.7 Warning state

判斷：

```text
eta >= now && eta <= now + warningWindowMinutes
```

UI：

- warning window 內且 data_basis 是 liveboard 時，使用 alert tone。
- timetable-only 可以提示 `班表預估`，不要過度警示。
- 沒有列車時顯示 `SAFE`，但不代表鐵路官方安全狀態，只代表目前 horizon 內沒有預測列車。

### 7.8 Optional: 本機通知

第一版可以先不做背景通知。若要做，應放在 Phase 2。

限制：

- App 不定時自動打 API，因此背景通知只能根據使用者最後一次選取與刷新取得的 envelope 排程 local notification。
- 如果使用者長時間不刷新，通知可能 stale。

Phase 2 設計：

- 使用 `flutter_local_notifications`。
- 使用者選取 crossing 後，可選擇 `接近時提醒`。
- 對 next/following records 排 local notification。
- Refresh 後重新排程。
- 顯示 `此提醒基於最後更新 HH:mm:ss`。

## 8. Flutter 方法與架構設計

### 8.1 技術選型

建議：

- Flutter stable。
- State management: `riverpod`。
- Immutable models: `freezed` + `json_serializable`。
- HTTP: `dio` 或 `http`。第一版用 `dio` 較方便 timeout/interceptor。
- Map: `flutter_map` + `latlong2`。
- Local cache: `hive` 或 `shared_preferences`。Catalog 建議 `hive`。
- Secure config: `--dart-define=API_BASE_URL=...`。
- Tests: `flutter_test` + repository mock。

### 8.2 分層架構

建議採用 feature-first + clean-ish layers，不要過度抽象。

```text
lib/
  main.dart
  app.dart
  core/
    config/
      app_config.dart
    network/
      api_client.dart
      api_error.dart
    time/
      clock.dart
      countdown_formatter.dart
    theme/
      app_theme.dart
      app_colors.dart
      app_spacing.dart
  features/
    crossings/
      data/
        crossing_api.dart
        crossing_cache.dart
        crossing_repository.dart
        dto/
          crossing_feature_dto.dart
          crossing_properties_dto.dart
      domain/
        crossing.dart
        crossing_detail.dart
        station_position.dart
      presentation/
        crossing_search_controller.dart
        crossing_catalog_controller.dart
        widgets/
          search_bar_control.dart
          search_sheet.dart
          crossing_marker_layer.dart
          crossing_summary_card.dart
    predictions/
      data/
        prediction_api.dart
        prediction_repository.dart
        dto/
          prediction_envelope_dto.dart
          prediction_record_dto.dart
      domain/
        prediction_envelope.dart
        prediction_record.dart
        prediction_runtime_state.dart
        train_slot.dart
      application/
        prediction_session_controller.dart
        train_slot_builder.dart
        last_passed_tracker.dart
      presentation/
        widgets/
          alert_hero_card.dart
          train_slot_card.dart
          stop_timing_pair.dart
          countdown_pill.dart
          data_source_badges.dart
    map/
      presentation/
        map_home_page.dart
        map_controller_adapter.dart
        map_layers.dart
    settings/
      settings_page.dart
      diagnostics_sheet.dart
```

### 8.3 State providers

建議 providers：

```text
apiClientProvider
appConfigProvider
clockProvider
crossingRepositoryProvider
predictionRepositoryProvider
crossingCatalogControllerProvider
selectedCrossingControllerProvider
predictionSessionControllerProvider
searchControllerProvider
mapCameraControllerProvider
```

核心 state：

```dart
class CrossingCatalogState {
  final bool isLoading;
  final List<Crossing> crossings;
  final List<CountyGroup> countyGroups;
  final Object? error;
  final DateTime? lastUpdatedAt;
}

class SelectedCrossingState {
  final String? crossingId;
  final Crossing? base;
  final CrossingDetail? detail;
  final bool isLoadingDetail;
  final Object? error;
}

class PredictionSessionState {
  final String? crossingId;
  final PredictionEnvelope? envelope;
  final PredictionRecord? lastPassedRecord;
  final Set<String> processedKeys;
  final DateTime now;
  final bool isLoading;
  final Object? error;
  final DateTime? receivedAt;
}
```

### 8.4 Repository responsibilities

CrossingRepository：

- `Future<List<Crossing>> loadCatalog({bool forceRefresh = false})`
- `Future<CrossingDetail> getDetail(String crossingId)`
- `Future<void> clearCache()`

PredictionRepository：

- `Future<PredictionEnvelope> getPredictions(String crossingId, PredictionQuery query)`

SearchController：

- `List<SearchSuggestion> buildSuggestions(String query)`
- `List<Crossing> filterCrossings(SearchSelection selection)`

PredictionSessionController：

- `selectCrossing(String crossingId)`
- `refresh()`
- `tick(DateTime now)`
- `clear()`

TrainSlotBuilder：

- `TrainSlots build(PredictionSessionState state)`
- 回傳 previous/next/following 三個 slot。

LastPassedTracker：

- `prime(envelope, now)`：把舊 ETA 標記 processed，但不回填上一班。
- `update(envelope, now, processedKeys)`：回傳 newly passed 與更新後 state。

### 8.5 DTO 與 domain mapping

DTO 要忠實對應 API snake_case。

Domain 可以改成 camelCase。

範例：

```dart
class PredictionRecord {
  final String trainNo;
  final String? trainType;
  final int? direction;
  final String? originStationName;
  final String? destinationStationName;
  final String? previousStopStationName;
  final DateTime? previousStopDeparture;
  final String? nextStopStationName;
  final DateTime? nextStopArrival;
  final String upstreamStationId;
  final String downstreamStationId;
  final DateTime eta;
  final String dataBasis;
  final String? ratioSource;
  final String? stationPairSource;
  final double segmentRatio;
}
```

解析注意：

- 後端 datetime 帶 timezone，Flutter parse 後需保留 local conversion。
- UI 顯示使用臺灣時間格式。
- `eta`、`previous_stop_departure`、`next_stop_arrival` 都要能處理 null 或 parse 失敗。

## 9. 手機端資料流

### 9.1 App start data flow

```text
App start
  -> CrossingCatalogController.load()
  -> CrossingRepository.loadCatalog()
  -> local cache first
  -> GET /api/crossings
  -> update catalog state
  -> SearchController builds county/station groups
  -> MapView renders markers
```

### 9.2 Select crossing data flow

```text
User taps marker/search result
  -> SelectedCrossingController.select(id)
  -> PredictionSessionController.select(id)
  -> Future.wait([
       CrossingRepository.getDetail(id),
       PredictionRepository.getPredictions(id, horizon=120, recent=10, warning=5),
     ])
  -> PredictionSessionController.primeRuntime(envelope)
  -> MapView focuses selected crossing + stations
  -> WatchSheet opens medium snap
```

### 9.3 Countdown data flow

```text
Timer.periodic(1s)
  -> PredictionSessionController.tick(now)
  -> LastPassedTracker.update()
  -> TrainSlotBuilder.build()
  -> UI rebuilds hero + cards
```

No API call in this flow.

### 9.4 Manual refresh data flow

```text
User taps 更新
  -> PredictionSessionController.refresh()
  -> GET /api/predictions/{selectedId}
  -> keep lastPassedRecord
  -> prime old records as processed
  -> update envelope
  -> rebuild UI
```

## 10. 品質與測試計畫

### 10.1 Unit tests

必測：

- `CountdownFormatter`：未來、現在、過去、秒級顯示。
- `TrainSlotBuilder`：下一班、第二班補足邏輯。
- `LastPassedTracker`：
  - 初始 envelope 不回填上一班。
  - ETA 跨過 now 後更新上一班。
  - 同一 train key 不重複更新。
  - refresh 後不把已過去資料塞入上一班。
- `SearchController`：county/station/crossing 搜尋。
- DTO parse：prediction envelope、crossing feature、null fields。
- Warning window 判斷。

### 10.2 Widget tests

必測：

- No selected crossing empty state。
- Prediction loading state。
- AlertHeroCard 顯示秒級現在/預計時間。
- TrainSlotCard 顯示 previous/next stop timing。
- 上一班初始空狀態。
- Error state 有 retry。
- Search sheet suggestions。

### 10.3 Integration tests

使用 mocked API server 或 repository fake。

情境：

1. App 啟動 -> 顯示 markers。
2. 搜尋 `四叉巷` -> 選取 -> 顯示 next/following。
3. Timer 推進跨過 next ETA -> next 變上一班。
4. 點刷新 -> 不清掉上一班。
5. API 失敗 -> 顯示錯誤但保留舊資料。

### 10.4 Golden tests

建議 golden：

- Alert hero scheduled。
- Alert hero live warning。
- Schedule slots normal。
- Schedule slots with empty previous。
- Search sheet。
- Crossing detail expanded。

## 11. Performance 設計

Catalog 約數百筆可定位 crossing，Flutter 第一版可直接全部載入記憶體。

地圖效能：

- 405 個 marker 對 Flutter Map 可接受。
- 若未來 marker 超過數千，才導入 clustering。
- Marker widget 盡量輕量，不放複雜文字。

Timer 效能：

- 每秒只更新 selected crossing 的 prediction session。
- 不全域 rebuild map。
- Countdown widgets 可用 provider select 或小範圍 Consumer 降低 rebuild。

Cache：

- Catalog cache：保留最近成功版本。
- Detail cache：以 crossingId map 暫存。
- Prediction 不長期 cache，最多保留 selected session。

## 12. 安全、隱私與權限

第一版不需要登入。

Location permission：

- 可選功能，不應阻擋主流程。
- 只有使用者點 `定位我附近` 才請求定位權限。
- 拒絕定位後仍可搜尋/選取。

Network：

- API base URL 透過 build config 注入。
- Production 必須使用 HTTPS。
- Timeout 建議 8 至 12 秒。

資料授權：

- OSM attribution 必須在地圖畫面可見。
- Settings 內提供資料來源說明。

## 13. 後端 production 前置需求

Flutter App 上架或實機外網使用前，需要處理以下後端部署項目：

- 將 FastAPI 部署到可公開存取的 HTTPS domain。
- 設定 CORS 與 mobile app 允許來源策略。
- 針對 TDX rate limit 保持 cache-first 與 fallback。
- 設定 server-side logging，方便追查錯誤預測。
- 增加 API version，例如 `/api/v1/...`，避免 mobile release 後 contract 破壞。
- 提供 health endpoint 給 App diagnostics。
- 若未來要 push notification，需要後端排程或推播服務；第一版不包含。

## 14. 實作里程碑

### Phase 0: Flutter 專案初始化

成果：

- 建立 Flutter app。
- 設定 lint、formatter、theme。
- 設定 API base URL。
- 建立 core network client。
- 建立基本 app shell。

驗收：

- App 可啟動。
- 可打 health endpoint 或 crossings endpoint。

### Phase 1: API models 與 repository

成果：

- Crossing DTO/domain。
- Prediction DTO/domain。
- CrossingRepository。
- PredictionRepository。
- Catalog local cache。

驗收：

- Unit tests 覆蓋 JSON parse。
- 可在 debug screen 列出 crossing count。

### Phase 2: Map Home 與搜尋

成果：

- OSM map。
- Crossing markers。
- SearchBarControl。
- Search Sheet。
- County/station/crossing local search。
- Focus bounds。

驗收：

- 可搜尋 `四叉巷` 並聚焦。
- 可點 marker 選取 crossing。

### Phase 3: Watch Sheet 與預測倒數

成果：

- Crossing summary。
- Alert hero。
- Schedule slots。
- Manual refresh。
- Local countdown timer。
- Session-local 上一班 tracker。

驗收：

- 選取 crossing 後顯示下一班與第二班。
- App 初始上一班為空。
- 推進時間跨過 ETA 後上一班更新。
- 點更新不清掉上一班。
- Timer 不打 API。

### Phase 4: Detail、狀態與錯誤處理

成果：

- Crossing detail expanded section。
- Data source badges。
- Loading/empty/error/stale states。
- Offline catalog cache fallback。
- Diagnostics sheet。

驗收：

- API 失敗時保留舊 predictions。
- 可清除 cache。
- 可看到 ratio source 與 station pair source。

### Phase 5: Polish 與 release readiness

成果：

- Accessibility labels。
- Golden tests。
- Android/iOS icon 與 app name。
- Production API config。
- OSM attribution 檢查。
- Real device testing。

驗收：

- Android 實機可使用。
- iOS simulator 可使用。
- 低網速與 API error 不會 crash。
- 主要畫面在 360dp 寬度不重疊。

## 15. MVP 範圍與暫不做項目

MVP 必做：

- 地圖。
- 搜尋。
- 選取平交道。
- 下一班 / 第二班 / 上一班。
- 秒級倒數。
- Previous/next stop timing。
- 手動刷新。
- 資料來源 badge。
- 基本 cache 與錯誤處理。

MVP 暫不做：

- 帳號系統。
- 收藏同步。
- 背景自動輪詢。
- Push notification。
- 在 Flutter 端重新實作 ETA 演算法。
- Manual OSM mapping editor。
- 管理後台功能。

Phase 2 可做：

- 我的常用平交道。
- 附近平交道。
- Local notification。
- Historical reliability diagnostics。
- 多平交道 watch list。

## 16. 主要風險與對策

### 16.1 TDX rate limit

風險：使用者頻繁刷新造成後端壓力。

對策：

- 前端 refresh button debounce，例如 5 秒內不可重複點。
- 後端繼續 cache-first。
- UI 顯示最後更新時間，避免使用者一直點。

### 16.2 使用者誤解 SAFE

風險：`SAFE` 被解讀成官方安全保證。

對策：

- 文案改成 `目前沒有預測列車` 或在 secondary text 說明 `120 分鐘內沒有接近列車`。
- 不使用過度權威的安全用語在正式版；若保留 SAFE，需加說明。

### 16.3 上一班 session-local 行為被誤解

風險：使用者以為上一班是歷史查詢。

對策：

- 空狀態明確寫 `本次開啟後尚未記錄到通過列車`。
- Detail tooltip 說明上一班是 App 本次追蹤結果。

### 16.4 時間顯示誤差

風險：API generated_at、server clock、device clock 有差異。

對策：

- UI 顯示 device now 與 ETA 秒級時間。
- 後端 datetime 必須帶 timezone。
- 測試 DateTime parsing 與 Asia/Taipei 顯示。
- Diagnostics 顯示 envelope generated_at 與 receivedAt。

### 16.5 Map tile 授權與流量

風險：直接使用 public OSM tile 在 production 可能違反使用政策或流量不穩。

對策：

- MVP development 可用 public OSM tile。
- Production 前評估商用 tile provider 或自建 tile cache。
- 必須顯示 attribution。

## 17. 第一版驗收清單

功能驗收：

- App 啟動後可以看到臺灣地圖與平交道 marker。
- 可以搜尋縣市、車站、平交道。
- 點選平交道後會顯示 crossing summary。
- 點選平交道後只呼叫一次 detail + predictions。
- 倒數每秒更新但不呼叫 API。
- 手動刷新只呼叫 predictions。
- 上一班初始為空。
- 下一班跨過 ETA 後，上一班更新為該班列車。
- 下一班與第二班顯示 previous/next stop timing。
- 四叉巷這類 skip-stop case 顯示後端修正後的 ETA。

UI 驗收：

- 360dp 寬度不重疊。
- 主要按鈕 touch target 至少 44dp。
- Bottom sheet 不遮住 selected marker 的關鍵位置。
- 時間顯示含秒。
- 空狀態文案清楚。
- Error state 可 retry。

測試驗收：

- Unit tests 覆蓋 DTO、search、countdown、last passed tracker。
- Widget tests 覆蓋 alert hero、train slot、empty states。
- Integration test 覆蓋 select crossing -> prediction -> pass ETA -> previous slot update。
