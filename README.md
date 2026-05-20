# CrossRadar

Python prototype for estimating whether a TRA train is about to pass a selected level crossing.

cd c:/Users/JasonHong/Desktop/CODE/_Project/CrossRadar && python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

cd c:/Users/JasonHong/Desktop/CODE/_Project/CrossRadar && python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001



官方平交道清冊成功抓取並正規化，共 418 筆。
OSM Overpass 成功抓出台灣 level crossing 與關聯鐵道、道路資料，共 1900 個 OSM crossing features。
官方清冊與 OSM 成功匹配出 380 個可定位的 curated crossings。
自動測試已通過，結果是 5 passed。
API 已實測可用，crossings detail 能回 station ids 與 segment ratio。
prediction endpoint 已實測回出非空 ETA。驗證 crossing 為暖暖街-宜蘭線-k001396，在 180 分鐘 horizon 下回出 10 筆 prediction。
TDX 的 station 與 timetable 已落地快取到 stations.json 與 today_timetables.json。
這台機器對外部 HTTPS 有憑證鏈問題，程式已補 SSL fallback；另外 TDX 在本次驗證過程中確實出現過 429，所以 client 已補成本地快取優先、liveboard 限流時退回 timetable-only 預測，不會整條鏈直接失敗。