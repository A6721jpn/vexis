# VEXIS 開発ガイド

**Version:** 1.4.1  
**Date:** 2026-01-18

本ドキュメントは、**VEXIS-CAE** 自動解析システムのアーキテクチャ、設計思想、および実装の詳細を記述したものです。開発エンジニアがコードベースを迅速に理解し、修正・拡張を行うための参考資料となります。

---

## 1. システム概要

**VEXIS-CAE** は、ゴム製キーキャップ形状に対する有限要素解析（FEA）を自動化するパイプラインアプリケーションです。CAD（STEP ファイル）からシミュレーション結果（`.csv`/`.png`/`.xplt`）まで、一連のワークフローを全自動で実行します。

### 動作モード

| `モード`     | `説明`                                                               |
| :----------- | :------------------------------------------------------------------- |
| `GUI モード` | `gui_main.py` から起動。PySide6 ベースのデスクトップアプリケーション |
| `CLI モード` | `main.py` から起動。コマンドラインでのバッチ処理用                   |

### コアワークフロー

```text
[STEP CAD] → [Mesh Generation] → [FEBio Prep] → [Solver] → [Result Extraction]
     ↓              ↓                  ↓              ↓              ↓
  input/         temp/*.vtk       temp/*.feb      solver/       results/
```

1. **入力**: CADファイル（`.stp`/`.step`）を `input/` に配置
2. **メッシュ生成**: STEP → ハイブリッドメッシュ（`.vtk`）に変換
3. **FEBio準備**:
   - テンプレートファイル（`template.feb`）から物理条件・材料・境界条件を読み込み
   - 新規メッシュをテンプレートにスワップ
   - NodeSets/Surfaces を幾何学ルールで再構築
   - メッシュを正しい座標位置にアライメント
4. **ソルバー実行**: `FEBio` ソルバーをサブプロセスで実行
5. **結果抽出**: ログファイルから荷重-変位曲線を抽出、3Dコンターマップを生成

---

## 2. ディレクトリ構造

```text
vexis/
├── gui_main.py              # GUI版エントリーポイント (PySide6)
├── main.py                  # CLI版エントリーポイント
├── analysis_helpers.py      # ワーカー関数 (Mesh/Prep/Solver/Extract)
├── build.py                 # PyInstallerビルドスクリプト
├── template2.feb            # マスターFEBioシミュレーション設定
├── requirements.txt         # Python依存ライブラリ
│
├── config/                  # 設定ファイル群
│   ├── config.yaml          # メイン設定 (メッシュサイズ、解析パラメータ)
│   └── material.yaml        # 材料定義
│
├── input/                   # STEP CADファイル配置ディレクトリ
├── temp/                    # 一時ファイル (.vtk, .feb)
├── results/                 # 解析結果出力先
├── solver/                  # FEBio実行ファイル格納
│
├── src/
│   ├── version.py           # バージョン定義
│   ├── app_logger.py        # ロギング設定
│   │
│   ├── gui/                 # [GUIモジュール]
│   │   ├── main_window.py       # メインウィンドウ
│   │   ├── job_manager.py       # ジョブ管理（スケジューラ）
│   │   ├── about_dialog.py      # バージョン情報ダイアログ
│   │   ├── file_watcher.py      # ファイル監視
│   │   ├── utils.py             # ユーティリティ
│   │   ├── panels/              # UI パネル群
│   │   │   ├── step_viewer.py       # STEP 3Dプレビュー
│   │   │   ├── mesh_preview.py      # メッシュプレビュー
│   │   │   └── contour_viewer.py    # 結果コンターマップ
│   │   ├── models/              # データモデル
│   │   └── styles/              # QSSスタイルシート
│   │
│   ├── mesh_gen/            # [メッシュ生成モジュール]
│   │   ├── main.py              # メッシュ生成エントリー
│   │   ├── geometry.py          # ジオメトリ処理
│   │   ├── core_mesh.py         # コア領域メッシュ生成
│   │   ├── ring_mesh.py         # リング領域メッシュ生成
│   │   ├── config.py            # メッシュ設定パーサー
│   │   └── utils.py             # ユーティリティ
│   │
│   ├── mesh_swap/           # [FEBio統合モジュール]
│   │   ├── mesh_replacer.py     # メッシュスワップ＆アライメント
│   │   ├── set_reconstructor.py # NodeSet/Surface再構築
│   │   ├── geometry_utils.py    # 幾何判定関数
│   │   └── result_analysis/     # 結果解析サブモジュール
│   │
│   ├── icons/               # アプリケーションアイコン
│   └── libs/                # ベンダー化ライブラリ (waffleiron等)
│
├── doc/                     # ドキュメント
├── dev_log/                 # 開発ログ
└── test/                    # テストコード
```

---

## 3. 主要コンポーネント詳細

### 3.1. GUI コントローラー (`src/gui/main_window.py`)

- **役割**: ユーザーインターフェースの管理
- **機能**:
  - STEP ファイルのドラッグ＆ドロップ読み込み
  - ジョブキュー管理とバッチ実行
  - リアルタイム進捗表示
  - 3D プレビュー（STEP/メッシュ/結果コンター）

### 3.2. ジョブマネージャー (`src/gui/job_manager.py`)

- **役割**: 解析ジョブのスケジューリングと実行管理
- **機能**:
  - 非同期ジョブ実行（QThread）
  - キャンセル・スキップ機能
  - 進捗シグナル発行

### 3.3. 解析ヘルパー (`analysis_helpers.py`)

- **役割**: Python と外部ツールのブリッジ
- **主要関数**:
  - `run_meshing()`: メッシュ生成をサブプロセスで実行
  - `run_integration()`: FEBio ファイル準備
  - `run_solver_and_extract()`: FEBio ソルバー実行＋リアルタイムログパース

### 3.4. メッシュ生成 (`src/mesh_gen/`)

- **役割**: STEP から高品質ハイブリッドメッシュを生成
- **エンジン**: `gmsh` API + `felupe`
- **出力**: `.vtk` ファイル
- **特徴**:
  - コア領域（Hex）＋リング領域（Tet）のハイブリッド構造
  - アダプティブメッシュサイズ対応

### 3.5. メッシュスワップ (`src/mesh_swap/`)

VEXIS で最も複雑なロジックを持つモジュールです。

#### A. メッシュアライメント（Min-XYZ マッチング）

新規メッシュをテンプレートに注入する際、座標系を合わせる必要があります。

```text
Shift Vector = Old_Min - New_Min
```

- テンプレート内の**旧メッシュ**のバウンディングボックス最小点を取得
- **新メッシュ**の最小点を計算
- 差分ベクトルで新メッシュを平行移動

#### B. セット再構築 (`set_reconstructor.py`)

Node ID / Element ID は変化するため、ID リストに依存せず**幾何学ルール**で再構築します。

| `戦略`                  | `用途`                     | `ロジック`                               |
| :---------------------- | :------------------------- | :--------------------------------------- |
| `Strategy A (相対境界)` | `同一パーツ上の自己接触面` | `メッシュ寸法に対する相対座標で領域定義` |
| `Strategy B (近接判定)` | `異なるパーツ間の相互作用` | `ターゲットパーツへの距離で面を選択`     |

---

## 4. 設定ファイル

### `config/config.yaml`

```yaml
mesh:
  size: 0.8           # メッシュサイズ (mm)
  refinement: true    # アダプティブ細分化
  
analysis:
  total_stroke: 1.5   # 押し込み量 (mm)
  time_steps: 20      # 時間ステップ数
  num_threads: 4      # 並列スレッド数
  contact_penalty: 5.0
```

### `config/material.yaml`

材料パラメータ（超弾性材料モデル）を定義します。

---

## 5. 開発者向け修正ガイド

### メッシュ解像度を変更したい場合

`config/config.yaml` の `mesh.size` を編集してください。

### 物理条件（材料、境界条件）を変更したい場合

`template2.feb` を FEBio Studio またはテキストエディタで編集してください。

> [!WARNING]
> テンプレート内の Named Selections（NodeSets/Surfaces）の名前は変更しないでください。  
> `set_reconstructor.py` がこれらの名前に依存しています。

### ログ出力を変更したい場合

- コンソール形式: `main.py` → `update_status`
- FEBio ログ解析: `analysis_helpers.py` → `run_solver_and_extract`

### 「Negative Jacobian」や接触エラーが発生した場合

`src/mesh_swap/set_reconstructor.py` を確認してください。新しい形状のアスペクト比が大きく変わった場合、Strategy A の相対境界パラメータの調整が必要になることがあります。

---

## 6. 既知の制約事項

| `制約`             | `詳細`                                      |
| :----------------- | :------------------------------------------ |
| `対応OS`           | `Windows のみ（msvcrt 依存）`               |
| `入力ファイル`     | `.stp` または `.step` 形式のみ`             |
| `テンプレート依存` | `template.feb 内に "RUBBER" パーツ名が必要` |

---

## 7. ビルド手順

```powershell
# 開発環境セットアップ
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 実行ファイルビルド
python build.py
```

出力先: `out/VEXIS-CAE/`

---

*ガイド終了*
