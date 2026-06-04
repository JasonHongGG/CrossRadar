# CrossRadar PhoneApp

CrossRadar PhoneApp 是最終產品端的 Flutter Android app。它不呼叫 WebApp prediction API，而是直接使用 TDX runtime snapshots，加上 `assets/data/crossradar_mobile_bundle.json` 內的 OSM runtime ratios、station-pair projections 與 calibration metadata，在裝置端完成預測。

## Runtime contract

- PhoneApp 和 WebApp 是獨立產品/實驗場關係；WebApp 只作為資料匯出、replay oracle 與校準研究工具。
- prediction 時間基準固定為 `Asia/Taipei`，timetable HH:mm 與 TDX `UpdateTime` 都以台灣鐵路服務日解讀。
- 每次 prediction 必須同時取得 liveboards、today timetables、today train-info；任一必要來源不完整時回 `snapshot_incomplete`，不靜默產生正常預測。
- runtime ratio 只接受 mobile bundle 內已匯出的 OSM along-track ratios；PhoneApp 不在裝置端重建 WebApp 的 OSM rail graph。
- prediction record 會帶 debug trace，包含 selected stop-pair、ratio、delay source/seconds、travel profile、anchor source、calibration offset 與 ETA，用於與 WebApp replay fixture 比對。
- calibration rules 只在 WebApp readiness gate 通過後匯入 bundle；目前 bundle 可能只有 observation/readiness metadata 而沒有可套用 rules。

## Bundle workflow

```bash
cd c:/Users/JasonHong/Desktop/CODE/_Project/CrossRadar/WebApp
PYTHONPATH=. python scripts/export_mobile_bundle.py --output ../PhoneApp/assets/data/crossradar_mobile_bundle.json
python scripts/audit_mobile_bundle_accuracy.py --bundle ../PhoneApp/assets/data/crossradar_mobile_bundle.json
python scripts/audit_mobile_calibration_readiness.py --bundle ../PhoneApp/assets/data/crossradar_mobile_bundle.json
```

The bundle schema v3 metadata includes a `prediction_contract` block that records required snapshot sources, railway time zone, OSM-only ratio scope, projection counts, calibration readiness, and trace fields expected for parity checks.

## Local credentials

```bash
cd c:/Users/JasonHong/Desktop/CODE/_Project/CrossRadar/PhoneApp
dart run tool/sync_env_credentials.dart
```

This writes ignored local defaults into `assets/config/default_credentials.json` from the repository `.env` file.

## Test

```bash
cd c:/Users/JasonHong/Desktop/CODE/_Project/CrossRadar/PhoneApp
flutter test
flutter analyze
```

## Build

```bash
cd c:/Users/JasonHong/Desktop/CODE/_Project/CrossRadar/PhoneApp
flutter build apk --debug
```

## Android 12+ Splash Screen Quirks

在 Android 12 以上版本 (特別是 Samsung OneUI)，系統強制會在 App 啟動的瞬間插入一個系統層級的 Splash Screen。如果沒有特別處理，它會抓取 Launcher Icon (狗狗) 並且強制包在一個白色圓角底框 (Squircle) 內，導致在進入 Flutter 的 `LaunchScreen` (也是狗狗，但從小放大) 時產生「先卡死板圖卡、再跳動畫」的視覺斷層。

**解決方案 (目前已實作)**：
為了達成 100% 無縫、直接進入精美動畫的體驗：
1. 已經在原生 Android 的 `values-v31/styles.xml` 與 `values-night-v31/styles.xml` 中，將 `android:windowSplashScreenAnimatedIcon` 強制設定為 `@android:color/transparent`。
2. 這會欺騙 Android 系統畫出一個**完全沒有圖標**的純色啟動畫面 (`#EEF6FF` 或 `#121827`)。
3. 這樣一來，啟動時只會看到一瞬間的純色背景，緊接著 Flutter UI 準備好後，您的精美縮放動畫就會如同無中生有般流暢演出。

> **⚠️ 注意**：因為 Android 桌面程式對 Splash Screen 有極強的快取，當您修改這些底層 XML 後，**必須完全解除安裝 App (Uninstall)** 並重新 `flutter run`，系統才會吃到這項透明設定。
