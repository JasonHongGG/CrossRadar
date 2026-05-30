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
