# VEXIS-CAE Manual JA

本ドキュメントでは、環境構築からCADデータの準備、GUIを用いた解析実行までの一連の流れを解説します。

---

## Step1. 環境構築

> [!TIP]
> **ポータブルビルド版（EXE版）を使用する場合**: 以下の手順（FEBio Studioの個別インストール）は不要です。そのまま **Step 2** へ進んでください。

VEXIS-CAEをPythonから直接実行するには、ソルバーである **FEBio Studio** のインストールが必要です。


### 1-1. FEBio Studioのインストール
1. [FEBio Software Center](https://febio.org/downloads/) から、OSに合わせた最新の FEBio Studio をダウンロードします。
2. インストーラーを実行し、デフォルトのパスにインストールします。

### 1-2. パスの確認と設定
VEXIS-CAEは `config/config.yaml` 内の `febio_path` を参照します。

> ### 注意  
> デフォルトでは `C:\Program Files\FEBioStudio\bin\febio4.exe` が指定されています。異なる場所にインストールした場合は、この項目を書き換えてください。

<!-- [SCREENSHOT REQUEST]
- 項目: FEBioの設定箇所
- 内容: config/config.yaml を開き、febio_path の行をハイライトしたエディタ画面
- ファイル名候補: img/setup_config_path.png
-->

---

## Step2. 解析データの準備 (CADデータ)

VEXIS-CAEは、STEP形式(`.stp`, `.step`)のファイルを入力として受け取ります。

### 2-1. モデリング時の注意点
> ### 注意: 
> かならず下記の条件を満たすようにSTEPファイルを準備してください！

- **モデリング**: STEPはソリッドを含まず、ラバードームの断面だけを含む**サーフェス**を準備して下さい。  
サーフェスを配置する場所に制限はありません。
- **配置**: 
断面サーフェスは必ず$YZ$平面に配置してください。VEXISはこのサーフェスを自動でZ軸まわりに回転押し出しし、ラバードーム形状に変換します。  
また、回転対称軸が $Z$ 軸に重なるように配置してください。
    - 底面が $Y$軸と原点に接するように配置してください。
    - 回転対称軸が $Z$ 軸に重なるように配置してください。
- **エクスポート**: STEP形式で保存し、`input` フォルダへ配置します。

<!-- [SCREENSHOT REQUEST]
- 項目: 推奨されるCADデータ形状
- 内容: CADソフト上での四分の一モデルの配置（Z=0接地面、Z軸中心）を示す画面
- ファイル名候補: img/cad_preparation.png
-->

---

## Step3. GUIリファレンス

VEXIS-CAEを起動すると以下のメイン画面が表示されます。

<!-- [SCREENSHOT REQUEST]
- 項目: メインGUI画面全体
- 内容: 起動直後の、空のジョブリストまたはジョブが並んでいる状態の全体画面
- ファイル名候補: img/gui_main_overview.png
-->

### 3-1. ツールバー操作
- **Start Batch (再生)**: ジョブリストの全解析を順次開始。
- **Gen Mesh (メッシュ生成)**: ソルバー解析を実行せずにメッシュ生成のみを実行し、3Dプレビューを表示。
- **Stop (一時停止)**: 実行中の解析を制止。
- **Skip (スキップ)**: 現在の解析を飛ばして次へ進む。
- **Refresh (更新)**: `input` フォルダを再走査。
- **Anti-sleep (目のアイコン)**: 有効化するとPCのスリープを防止。長時間バッチ処理時に便利。
- **Config (歯車)**: 解析設定 (`config.yaml`) を開く。
- **Material (波線)**: 材料設定 (`material.yaml`) を開く。

<!-- [SCREENSHOT REQUEST]
- 項目: ツールバーのズーム
- 内容: ツールバー部分を拡大し、各アイコンが識別できる状態
- ファイル名候補: img/gui_toolbar_detail.png
-->

---

## Step4. 解析の実行手順

### 4-1: ファイルの配置
作成した STEP ファイルを `input` フォルダにコピーします。

### 4-2: アプリの起動と確認
GUIを起動すると、左側の **Jobs List** にファイルが表示されます。  
ジョブを選択すると中央のパネルでSTEPの形状を確認できます。この段階ではSTEPを表示しているだけなので、断面サーフェスだけが表示されています。

<!-- [SCREENSHOT REQUEST]
- 項目: ジョブ選択と形状プレビュー
- 内容: ジョブリストから一つ選択し、右側の「STEP Geometry」タブで3D形状が表示されている状態
- ファイル名候補: img/workflow_preview.png
-->

### 4-3: 解析開始
ツールバーの **Start Batch** をクリックします。

### 4-4: 進捗の監視
解析中は **Progress/Log** 表示に切り替わり、計算ログがリアルタイムで流れます。

<!-- [SCREENSHOT REQUEST]
- 項目: 解析中のログ表示
- 内容: Progress/Log タブで FEBio の計算ログがスクロール表示されている状態
- ファイル名候補: img/workflow_running_log.png
-->

### 4-5: 結果の確認
解析完了後、**Result Viewer** タブで「荷重-変位グラフ」が表示されます。タブで3Dコンター表示へ切り替えることも可能です。コンター表示ではビュワー下部のスライダーで時系列で変形の様子や応力の進展を確認できます。スライダーはPCのパフォーマンスにより若干遅れて追従するケースがあります。

<!-- [SCREENSHOT REQUEST]
- 項目: 解析結果画面
- 内容: 解析完了後、Result Viewer タブでグラフ（Force-Stroke）が表示されている状態
- ファイル名候補: img/workflow_result_graph.png
-->

---

## Step5. 各種設定ファイルの編集

### 5-1. 解析条件 (config.yaml)
メッシュの細かさや押し込み量 (`total_stroke`)、計算ステップ数 (`time_steps`) などを変更できます。

### 5-2. 材料特性 (material.yaml)
ゴムの特性（Ogdenモデルの係数など）を材料名ごとに定義できます。定義した材料は解析条件のconfig.yamlで指定します。

<!-- [SCREENSHOT REQUEST]
- 項目: 材料編集画面
- 内容: Materialボタンで開いた material.yaml の編集画面
- ファイル名候補: img/setup_material_editor.png
-->
