# 作業ログ 2026-01-06

## 概要
VEXIS-CAE v1.2.0 → v1.3.0 リリース作業

## 作業内容

### ブランチ管理
- WAFFLEIRONブランチをmainへマージ
- 古いブランチ (AG-GUI, Anti-G, GPT-trial, SOLVER-INCLUDE) を削除
- V120, V121ブランチ作成

### バージョンアップ (v1.2.1 → v1.3.0)
- `src/version.py` 更新
- `config/config.yaml` ヘッダーコメント更新

---

## v1.2.0 - v1.2.1 作業 (午前)

### アンチスリープ機能 ✅
- `src/utils/sleep_manager.py` 新規作成
- ツールバーにアイコントグルボタン追加

### コンター図の滑らか表示 ✅
- `cell_data_to_point_data()` で節点平均化

---

## v1.3.0 作業 (午後)

### リファクタリング ✅
- **共通ジオメトリユーティリティ統合**: `src/utils/geometry.py` 新規作成
  - `calculate_bounding_box`, `extract_boundary_faces`, `build_kdtree` など
- **SetReconstructor戦略パターン化**: `ReconstructionStrategy` 抽象クラス導入
- **GUIユーティリティ分離**: `src/gui/utils.py` へ `load_icon` 抽出

### バグ修正 ✅
- **接触面再構築エラー**: `geometry.py` の `if not elements:` を `len(elements) == 0` に修正
  - Hex20要素で `ambiguous truth value` エラー発生 → サーフェス全削除 → 接触破綻
  
### UI改善 ✅
- **グラフ動的リサイズ**: `FigureCanvasQTAgg` 埋め込みに変更
  - `_update_graph()`, `_plot_graph()`, `_show_no_graph_message()` 追加
- **Loading Overlay修正**: EXE環境での中央配置を `setGeometry` で明示指定

### 調査レポート作成 ✅
- `doc/febio_optimization_report.md` 作成
  - time_steps, dtol/etol, max_ups, 線形ソルバー選択のPros/Cons

---

## 変更ファイル一覧
| ファイル                                           | 変更内容                          |
| -------------------------------------------------- | --------------------------------- |
| `src/version.py`                                   | 1.3.0                             |
| `config/config.yaml`                               | ヘッダー更新                      |
| `src/utils/geometry.py`                            | 新規                              |
| `src/mesh_swap/geometry_utils.py`                  | リファクタ (再エクスポートのみ)   |
| `src/mesh_swap/set_reconstructor.py`               | Strategy パターン導入             |
| `src/gui/utils.py`                                 | 新規                              |
| `src/gui/main_window.py`                           | load_icon 外部化                  |
| `src/gui/panels/result_viewer.py`                  | FigureCanvas埋め込み, Overlay修正 |
| `src/mesh_swap/result_analysis/extract_results.py` | parse_rigid_body_data 追加        |
| `doc/febio_optimization_report.md`                 | 新規                              |
| `doc/release_notes.md`                             | v1.3.0 追加                       |
