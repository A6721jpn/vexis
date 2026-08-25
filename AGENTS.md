# VEXIS Agent Guide

このファイルは、VEXIS-CAE を触るエージェント向けの最初の読み物です。作業前にこの順で確認してください。

1. `README.md`: 実行方法と現行フォルダの概要。
2. `doc/Development_Guide.md`: アーキテクチャ、主要モジュール、FEBio 統合の設計意図。
3. `doc/workflow_guide_ja.md`: 入力 STEP の前提、GUI 操作、ユーザー向け解析フロー。
4. `doc/release_notes.md`: バージョン文脈。`src/version.py` と release notes/tag の状態がずれることがあるため、リリース状態を断定する前に両方を確認する。
5. 変更対象のコードと対応テスト。

## Project Summary

VEXIS-CAE は、ゴムドーム/キーキャップ形状の有限要素解析を自動化する Windows 向けアプリです。`.stp`/`.step` の断面サーフェスを `input/` に置き、メッシュ生成、FEBio 入力生成、ソルバー実行、荷重-変位結果と 3D 結果表示までを GUI または CLI で実行します。

主な入口は `gui_main.py` と `main.py` です。ワークフローの中核は `analysis_helpers.py`、GUI は `src/gui/`、メッシュ生成は `src/mesh_gen/`、FEBio テンプレートへのメッシュ差し替えと NodeSet/Surface 再構築は `src/mesh_swap/` にあります。

## Commands

開発環境は通常 Windows + Python 仮想環境です。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python gui_main.py
python main.py
python main.py --mesh-only
python main.py --skip-mesh
```

検証は、変更範囲に応じて最低限これを使います。

```powershell
python -m pytest test tests
```

Rust/Vulkan 統合まわりを触る場合は `build_rust.py` と `src/libs/vexis_vulkan_core/` を確認し、必要に応じて Rust 側のビルドも実行してください。`src/libs/vexis_vulkan_core/target/` は生成物です。

## Invariants

- STEP 入力は `.stp` または `.step` のみです。
- CAD 入力はソリッドではなく、ラバードーム断面のサーフェスを想定します。
- 断面は YZ 平面に置き、回転対称軸が Z 軸に重なる前提です。
- `config/config.yaml` の `mesh.revolve_angle` は現状 90 度固定です。
- `mesh.mesh_dimension` は 1 または 2 のみです。
- `analysis.total_stroke` は 0 禁止、`analysis.time_steps` は正数、`analysis.num_threads` は指定するなら 1 から 32、`analysis.contact_penalty` は 0 より大きく 20 未満です。
- `template2.feb` は中核テンプレートです。FEBio の Named Selections、NodeSet、Surface、SurfacePair、材料名、剛体拘束名を不用意に変えないでください。
- 特に `RUBBER`, `RUBBER_OBJ`, `KEYCAP`, `KEYCAP_OBJ`, `KEYCAP_PUSH`, `RUBBER_SELF_CONTACT` と関連 Surface 名はコードから参照されています。
- `src/mesh_swap/set_reconstructor.py` は ID リストではなく幾何ルールで NodeSet/Surface を再構築します。接触面や境界条件の変更では、必ずこのモジュールと `src/mesh_swap/mesh_replacer.py` を確認してください。

## Generated And Local Files

`input/`, `temp/`, `results/`, `logs/`, `solver/`, `build/`, `dist/`, `out/`, `.venv/`, `.pdfenv/`, Rust `target/`、FEBio ソースビルド作業領域、各種 `__pycache__/` はローカルまたは生成物です。Git に入れないでください。

古い生成物や退避したファイルは `obsolute/` に置きます。このフォルダ名は現状の退避先として使われており、`.gitignore` で Git 追跡対象外です。必要なものを戻す場合だけ中身を確認し、戻した理由を作業ログに残してください。

`src/libs/waffleiron` は外部ライブラリ扱いです。.xplt 読み込みや FEBio XML 連携の必要がない限り広範囲に変更しないでください。

## Development Notes

- 計画や作業メモは日本語で簡潔に書いてください。
- Markdown の表を使う場合は、既存の `.agent/rules/formatting.md` に合わせて、ヘッダーとセルの文字列をバッククォートで囲んでください。
- 作業ログを残す場合は `dev_log/work_summary_YYYYMMDD.md` の既存命名に合わせます。既存ログは削除せず、追記を基本にします。
- `doc/` はユーザー向け/開発者向けドキュメント、`dev_log/` は履歴、`obsolute/` は退避箱です。正本として参照する順番を混同しないでください。
- Git 作業では、既存の未コミット変更をユーザー作業として扱い、明示指示なしに戻さないでください。
