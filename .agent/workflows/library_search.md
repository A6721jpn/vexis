---
description: ユーザーの業務効率化要件を満たす最適なPythonライブラリを調査・選定するためのワークフロー
---

1. **要件定義 (Requirement Definition)**
   - ユーザーの実現したい自動化・効率化の内容をヒアリングする。
   - **Python** 環境であることを前提とし、必要なPythonバージョンや既存の依存関係との兼ね合いを確認する。
   - 「有名であること」よりも「目的に合致し、実用的に動作すること」を優先する方針を共有する。
2. **広範な候補探索 (Broad Search)**
   - `search_web` を使用し、解決したいタスクに関連するキーワード + "python library", "pypi", "github" 等で検索を行う。
   - 一般的な「おすすめ10選」だけでなく、以下の視点でニッチなライブラリも探す:
     - Github Topics (例: `topic:python`, `topic:automation`)
     - PyPI の特定 Classifier 検索結果
     - Tech Blog や Reddit (r/Python) での具体的な推奨事例 ("hidden gems")
   - **注意**: Star数が少なくても切り捨てない。更新頻度（直近1年以内のコミットなど）やREADMEの具体性を重視してリストアップする。
3. **詳細調査・ドキュメント確認 (Deep Dive)**
   - 選定した候補について詳細を確認する。
   - **Context7の活用**: メジャーな候補については `mcp_context7_resolve-library-id` -> `mcp_context7_query-docs` を試みる。
   - **ニッチな候補の場合**:
     - IDが見つからない可能性が高いため、PyPIのProjectリンクやGithubのREADME、`docs/` フォルダを `read_url_content` や `read_browser_page` (必要な場合) で直接読み込む。
     - 依存関係の軽さや、インストールが容易か（C拡張のビルド不要か等）もチェックする。
4. **検証実装 (Spike Checklist)**
   - ニッチなライブラリはドキュメント不備の可能性があるため、可能な限り動作確認を行う。
   - **実行環境の確認**:
     - ユーザーが既に仮想環境(venv)内にいる場合が多いため、無闇に新しいvenvを作成しない。
     - `sys.prefix != sys.base_prefix` 等で現在の環境を確認する。
   - **インストールの判断**:
     - 既存環境を汚したくない場合は、一時ディレクトリを作成して `python -m venv .venv` し、そこを使用するか、`uv` のようなツールがあれば `uv run --with [package] script.py` を検討する。
     - ユーザーの許可があれば、既存環境に直接 `pip install` しても良い。
   - **検証実行**:
     - 最も基本的なサンプルコード ("Hello World" 的なもの) を作成し、実行確認を行う。
   
   ```python
   # Example verification step
   # // turbo
   # # Check if we need to install
   # run_command("pip install [library_name]") 
   # run_command("python test_script.py")
   ```
5. **評価・推薦 (Evaluation & Proposal)**
   - 以下の基準で推奨ライブラリを決定する:
     - **適合度**: 「やりたいこと」が最小限のコードで実現できるか。
     - **導入コスト**: 余計な依存や複雑な設定が不要か。
     - **安定性**: 小規模でもメンテされているか（最終更新日）。
   - ユーザーには、「なぜこのライブラリ（たとえマイナーでも）を選んだか」という理由を、コードの具体例と共に提示する。