# 作業ログ 2026-01-06

## 概要
VEXIS-CAE v1.2.0 リリース準備

## 作業内容

### ブランチ管理
- WAFFLEIRONブランチをmainへマージ
- 古いブランチ (AG-GUI, Anti-G, GPT-trial, SOLVER-INCLUDE) を削除
- V120ブランチを新規作成

### バージョンアップ (v1.1.2 → v1.2.0)
- `src/version.py` 更新
- `config/config.yaml` ヘッダーコメント更新

### 新機能: アンチスリープ機能
- [ ] `src/utils/sleep_manager.py` 新規作成
- [ ] `MainWindow`ツールバーに「Keep Awake」チェックボックス追加
- [ ] チェックON時にPCスリープと画面OFFを防止

## 技術メモ
Windows API `SetThreadExecutionState` を使用してスリープを制御
