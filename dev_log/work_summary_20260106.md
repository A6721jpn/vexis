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
- `src/utils/sleep_manager.py` 新規作成
- ツールバーにアイコントグルボタン追加（終了ボタンの右隣）
- `eye-closed.svg` (OFF) / `eye-solid.svg` (ON) で状態を視覚表示
- クリックで切り替え、既存アイコンと同じ色味で実装
- ツールチップ: "Anti-sleep ON/OFF"
- アプリ終了時にスリープ設定を自動復元

### ドキュメント修正
- `dev_log/todo.md` のアダプティブメッシュMDリンクを相対パスに修正
- `doc/release_notes.md` v1.2.0セクション追加

## 技術メモ
Windows API `SetThreadExecutionState` を使用してスリープを制御
- `ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED`

## 変更ファイル
| ファイル                     | 変更内容             |
| ---------------------------- | -------------------- |
| `src/version.py`             | バージョン番号 1.2.0 |
| `config/config.yaml`         | ヘッダーコメント更新 |
| `src/utils/sleep_manager.py` | 新規作成             |
| `src/gui/main_window.py`     | アイコントグル追加   |
| `dev_log/todo.md`            | リンク修正           |
| `doc/release_notes.md`       | v1.2.0追加           |
