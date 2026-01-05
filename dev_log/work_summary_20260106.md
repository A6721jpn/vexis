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

### 新機能: アンチスリープ機能 ✅
- [x] `src/utils/sleep_manager.py` 新規作成
- [x] ツールバーにアイコントグルボタン追加（終了ボタンの右隣）
- [x] `eye-closed.svg` (OFF) / `eye-solid.svg` (ON) で状態を視覚表示
- [x] クリックで切り替え、既存アイコンと同じ色味
- [x] アプリ終了時にスリープ設定を復元

## 技術メモ
Windows API `SetThreadExecutionState` を使用してスリープを制御

## 変更ファイル
- `src/version.py` - バージョン番号更新
- `config/config.yaml` - ヘッダーコメント更新
- `src/utils/sleep_manager.py` - 新規作成
- `src/gui/main_window.py` - チェックボックスUI追加
