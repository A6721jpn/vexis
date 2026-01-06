# 作業ログ 2026-01-06

## 概要
VEXIS-CAE v1.2.0 → v1.2.1 リリース作業

## 作業内容

### ブランチ管理
- WAFFLEIRONブランチをmainへマージ
- 古いブランチ (AG-GUI, Anti-G, GPT-trial, SOLVER-INCLUDE) を削除
- V120ブランチを新規作成
- **V121ブランチを新規作成** (v1.2.1開発用)

### バージョンアップ (v1.1.2 → v1.2.0 → v1.2.1)
- `src/version.py` 更新
- `config/config.yaml` ヘッダーコメント更新

### 新機能: アンチスリープ機能 ✅ (v1.2.0)
- `src/utils/sleep_manager.py` 新規作成
- ツールバーにアイコントグルボタン追加（終了ボタンの右隣）
- `eye-closed.svg` (OFF) / `eye-solid.svg` (ON) で状態を視覚表示
- クリックで切り替え、既存アイコンと同じ色味で実装
- ツールチップ: "Anti-sleep ON/OFF"
- アプリ終了時にスリープ設定を自動復元

### 新機能: コンター図の滑らか表示 ✅ (v1.2.1)
- `src/gui/panels/result_viewer.py` を修正
- 応力・ひずみ（Cell Data）を節点データ（Point Data）に変換
- `cell_data_to_point_data()` により隣接要素間で滑らかなグラデーション表示を実現
- 変位と同様の視覚的品質を確保

### ドキュメント修正
- `dev_log/todo.md` のアダプティブメッシュMDリンクを相対パスに修正
- `doc/release_notes.md` v1.2.0, v1.2.1セクション追加

## 技術メモ
- Windows API `SetThreadExecutionState` を使用してスリープを制御
- PyVista `cell_data_to_point_data()` で節点平均化

## 変更ファイル
| ファイル                          | 変更内容             |
| --------------------------------- | -------------------- |
| `src/version.py`                  | バージョン番号 1.2.1 |
| `config/config.yaml`              | ヘッダーコメント更新 |
| `src/utils/sleep_manager.py`      | 新規作成             |
| `src/gui/main_window.py`          | アイコントグル追加   |
| `src/gui/panels/result_viewer.py` | コンター滑らか表示   |
| `dev_log/todo.md`                 | リンク修正           |
| `doc/release_notes.md`            | v1.2.0, v1.2.1追加   |
