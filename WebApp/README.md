# CrossRadar

CrossRadar 是一個以 FastAPI 後端加靜態前端組成的 TRA 平交道預測原型。現在的 runtime 架構只接受 curated crossing dataset 與 OSM 沿軌道路徑，不再退回官方公里、直線投影或中點去硬算 ETA。

## Runtime contract

- runtime 只處理 `data/crossings/crossings_curated.geojson` 內的 active crossings。
- crossing ratio 只接受 OSM along-track path；沒有可接受的 OSM path 時，prediction API 直接回 `available=false`。
- 更新採使用者觸發，不做背景 polling。
- 每次 prediction 會一起整理 crossing detail、station-scoped liveboards、當日 timetable、當日 train-info delay snapshot。
- 若其中任一必要來源無法取得完整 snapshot，API 會回 `snapshot_incomplete`，而不是靜默降級成不完整預測。
- `ratio-workspace.html` 現在是 debug-only 的 OSM path 診斷頁，不再混入官方公里或直線投影比較。

## Run

```bash
cd c:/Users/JasonHong/Desktop/CODE/_Project/CrossRadar/WebApp
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

啟動後開啟 `http://127.0.0.1:8000/`。

## Test

```bash
cd c:/Users/JasonHong/Desktop/CODE/_Project/CrossRadar/WebApp
python -m pytest
```

## Key endpoints

- `GET /api/crossings`: 回傳 runtime crossings 清單。
- `GET /api/crossings/stations`: 回傳車站概覽圖層。
- `GET /api/predictions/{crossing_id}`: 回傳選定 crossing 的 detail、prediction envelope、snapshot 狀態與列車預測。
- `GET /api/crossings/{crossing_id}/ratio-explanation`: 回傳 OSM path 診斷資料。
- `GET /api/system/overview`: 回傳 dataset 與本地 cache 概況。

## Snapshot and cache behavior

- TDX station、timetable、train-info 會落地到 `.runtime/tdx/`；station-scoped liveboards 會落地到 `.runtime/tdx/liveboards/`。
- prediction envelope 內的 `data_snapshot.sources` 會標示每個來源是來自 network、memory cache、parsed file cache、file cache 或 stale cache，並帶每個來源自己的 `timing_breakdown`。
- 主頁選取 crossing 時會先即時渲染 crossing card，再等待 prediction envelope；最新一次前端 `firstRenderMs` / `fullRenderMs` 會寫到 `window.__crossRadarLastSelectionLatency` 供本機觀察。
- 這台機器若遇到 HTTPS 憑證鏈問題，HTTP layer 仍保留 SSL fallback；若 TDX 出現 429，系統會優先重用本地 cache，但 freshness 與 source status 會明確暴露在 snapshot metadata 中。