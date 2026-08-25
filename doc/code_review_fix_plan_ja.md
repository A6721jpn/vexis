# コードレビュー修正 実装計画書(Codex 実施用)

- 作成日: 2026-07-02
- 対象: VEXIS-CAE リポジトリ全体(`src/libs/waffleiron` を除く)
- 目的: 2026-07-02 実施のコードレビューで確定した修正を、Codex が単独で安全に実施できるように手順化する。
- 行番号はすべて 2026-07-02 時点のワークツリー基準。実施時に多少ズレている可能性があるため、必ず前後のコードを確認してから編集すること。

## 0. 前提と実施ルール

### 0-1. 背景となる決定事項

- Rust/Vulkan 実装(`src/libs/vexis_vulkan_core`、`src/gui/panels/vulkan_widget.py`)は**今後デプロイされる**。削除せず、デプロイに耐える状態へ整備する方針とする。
- パッケージングは `build_rust.py` + `VEXIS-CAE-Rust.spec` に一本化する(旧 `build.py` は退役)。

### 0-2. 変更してはいけないもの(AGENTS.md の不変条件)

- `template2.feb` の Named Selections、NodeSet、Surface、SurfacePair、材料名、剛体拘束名(`RUBBER`, `RUBBER_OBJ`, `KEYCAP`, `KEYCAP_OBJ`, `KEYCAP_PUSH`, `RUBBER_SELF_CONTACT` など)。
- `src/libs/waffleiron/` 配下(外部ライブラリ扱い)。
- `obsolute/` 内の既存ファイル(退避箱。今回新規に入れるものはあるが、既存物の復活・削除はしない)。
- 現在の git 未コミット変更(多数の M ファイル)はユーザー作業なので、revert / stash / checkout で巻き戻さないこと。今回の修正はその上に積む。

### 0-3. 検証コマンド

各 Phase 完了ごとに、**vexis リポジトリのルートから**以下を実行する(テストは CWD 依存があるため、Phase 1-7 完了までルート実行が必須)。

```powershell
.\.venv\Scripts\activate
python -m pytest test tests   # Phase 4-5 のフォルダ統合後は: python -m pytest tests
```

GUI/CLI の起動確認(Phase 1・2・3 完了後に最低 1 回):

```powershell
python main.py --mesh-only    # input/ に .stp がある場合
python gui_main.py            # 起動してウィンドウが出ることを確認して閉じる
```

Rust 側を触った場合(Phase 2 完了後):

```powershell
# src/libs/vexis_vulkan_core で
python -m maturin develop --release
python -c "import vexis_vulkan_core; print('ok')"
```

### 0-4. コミットとログ

- Phase 単位でコミットする。コミット手順は `.agent/workflows/commit.md` に従う。
- 全 Phase 完了後、`.agent/workflows/devlog.md` に従い `dev_log/work_summary_YYYYMMDD.md` に作業サマリを追記する。

### 0-5. Phase 一覧

| `Phase` | `内容` | `リスク` |
| :--- | :--- | :--- |
| `1` | `正しさのバグ修正(7項目)` | `中(挙動が変わる箇所あり・いずれも安全側への変更)` |
| `2` | `Rust/Vulkan デプロイ準備(5項目)` | `低` |
| `3` | `デッドコード削除(8項目)` | `低(挙動不変)` |
| `4` | `ファイル・テスト整理(6項目)` | `低` |
| `5` | `低リスク品質改善(3項目)` | `低` |
| `保留` | `ユーザー判断待ち。Codex は触らない` | `-` |

---

## Phase 1: 正しさのバグ修正

### 1-1. ソルバー全候補起動失敗時の偽成功を防止

- **対象**: `analysis_helpers.py` の `run_solver_and_extract()`(`last_error_code = 0` の初期化は L376 付近、ループ後判定は L482)
- **問題**: `last_error_code` が 0 で初期化されるため、全候補で `subprocess.Popen` 自体が例外を投げて `continue` した場合、ループ後も 0 のままとなり結果抽出フェーズへ進む。`temp/rigid_body_data.txt` に前回ジョブの残骸があると偽の成功として処理される。
- **修正**: ソルバーが 1 度でも起動できたかを示すフラグを導入する。

```python
last_error_code = 0
solver_started = False          # 追加

for current_exe in valid_candidates:
    ...
    try:
        proc = subprocess.Popen(...)
        solver_started = True   # Popen 成功直後に追加
        ...
```

ループ後の判定を次に変更:

```python
if not solver_started or last_error_code != 0:
    return False
```

- **検証**: 既存テストが通ること。加えて `febio_path` に存在しない exe を指定し `solver/febio4.exe` も無い状態で実行し、`False`(GUI では「Solver failed」)になることを目視確認できればなお良い。

### 1-2. 到達不能な KeyboardInterrupt 分岐と重複クリーンアップの削除

- **対象**: `analysis_helpers.py` L489-519(`run_solver_and_extract()` の `except Exception as e:` ブロックと `finally`)
- **問題**:
  1. `KeyboardInterrupt` は `Exception` のサブクラスではないため、`except Exception` ブロック内の `isinstance(e, KeyboardInterrupt)` 判定(L503-504、L510-511)は絶対に成立しない到達不能コード。
  2. except ブロック内の `proc.kill()` / `solver_bar.close()`(L490-493)は直後の `finally`(L516-519)と重複。
- **修正**: except ブロックを以下のように簡素化する(`finally` はそのまま残す)。

```python
    except Exception as e:
        # Log error to global log if possible
        if log_path:
            try:
                with open(log_path, "a", encoding="utf-8") as f_err:
                    f_err.write(f"!!! Solver Exception: {str(e)} !!!\n")
            except OSError:
                pass

        if not progress_callback:  # CLI
            print(f"Solver error: {e}")

        raise
```

- **補足**: CLI の Ctrl+C(KeyboardInterrupt)はこの except を素通りし、`finally` で proc.kill された上で `main.py` 側の `except KeyboardInterrupt` に届く。これが正しい挙動であり、追加対応は不要。
- **検証**: 既存テスト。GUI からジョブ実行→Stop で正常に停止すること。

### 1-3. アウターリングメッシュの三角形混在をエラー化

- **対象**: `src/mesh_gen/ring_mesh.py` L117-127
- **問題**: 四角形化(recombination)が部分的に失敗して三角形と四角形が混在した場合、三角形は黙って捨てられ、穴の空いたリングメッシュが下流(回転押し出し→FEBio)へ流れる。現状エラーになるのは「全部三角形」のときだけ。
- **修正**: 三角形が 1 つでもあればエラーにする。既存の「triangles only」チェック(L120-124)を以下で置き換える。

```python
    if tri_count > 0:
        raise RuntimeError(
            f"Outer ring meshing produced {tri_count} triangle(s). "
            "Mixed or triangle-only meshes would leave holes after revolve. "
            "Adjust mesh_size or recombination options, or check geometry quality."
        )
```

`if not quads:` のチェック(L126-127)はそのまま残す。

- **検証**: 既存テスト+`python main.py --mesh-only` が正常な入力で従来どおり成功すること。

### 1-4. import フォールバック連鎖の除去(黙殺の禁止)

- **対象**:
  - `src/mesh_swap/mesh_replacer.py` L4-17
  - `src/mesh_swap/set_reconstructor.py` L4-7
- **問題**: `mesh_swap_automation.set_reconstructor` はこのリポジトリに存在しない旧構成のパッケージ名。全フォールバックが失敗すると print して `pass` するため `SetReconstructor` 未定義のまま進み、`replace_mesh()` 内の `except` で `reconstructor = None` に化けて「セット再構築なしの .feb」が黙って生成される。
- **修正**: 両ファイルとも try/except を撤廃し、通常の相対 import 1 本にする。

```python
# mesh_replacer.py
from .set_reconstructor import SetReconstructor

# set_reconstructor.py
from . import geometry_utils
```

- **補足**: `replace_mesh()` 内の `SetReconstructor` 初期化を包む try/except(L59-66)は「テンプレート構造の問題」を拾う正当な用途なので残してよい。
- **検証**: `python -m pytest test tests`(`tests/test_refactor_regressions.py` が SetReconstructor を直接使用している)。

### 1-5. ノード ID 再利用による再構築セット誤削除のガード

- **対象**: `src/mesh_swap/mesh_replacer.py`
  - `find_available_start_id()`(L27-38)
  - `replace_mesh()` 内の採番(L282)と `cleanup_orphans()` 呼び出し(L420)
- **問題**: 新ノード ID は「旧ノード削除後の残存ノード max+1」で採番される。現行 `template2.feb` は RUBBER_OBJ(16373〜)の後に MEMBRANE_OBJ(〜43019)があるため衝突しないが、**置換対象パートが最大 ID を持つテンプレート**では新 ID が旧 ID 範囲と数値衝突し、後段の `cleanup_orphans(tree, old_node_ids)` が再構築済みの NodeSet/Surface を「旧 ID 参照」と誤認して削除する。
- **修正**:
  1. `replace_mesh()` の採番箇所(L282)を以下に変更し、旧 ID 範囲を構造的に回避する。

```python
    start_node_id = find_available_start_id(tree, "node")
    if old_node_ids:
        start_node_id = max(start_node_id, max(old_node_ids) + 1)
    start_elem_id = find_available_start_id(tree, "elem")
```

  2. あわせて `find_available_start_id(tree, count, tag_type="node")` の**未使用引数 `count` を削除**し、シグネチャを `find_available_start_id(tree, tag_type="node")` にする(呼び出しは上記 2 箇所のみ)。
- **検証**: `tests/test_refactor_regressions.py` に以下の回帰テストを追加する。

```python
def test_replace_mesh_new_node_ids_do_not_collide_with_old():
    import numpy as np
    from src.mesh_swap.mesh_replacer import load_reference, replace_mesh

    template = Path(__file__).resolve().parents[1] / "template2.feb"
    tree = load_reference(str(template))

    # 旧 RUBBER_OBJ ノード ID を控える
    mesh = tree.getroot().find("Mesh")
    rubber = next(n for n in mesh.findall("Nodes") if n.get("name") == "RUBBER_OBJ")
    old_ids = {int(n.get("id")) for n in rubber.findall("node")}

    new_nodes = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=float)
    new_elems = [[0, 1, 2, 3, 4, 5, 6, 7]]

    nodes_mapping, _ = replace_mesh(tree, new_nodes, new_elems, "RUBBER_OBJ", "hex8")

    assert min(nodes_mapping.values()) > max(old_ids)
```

### 1-6. `build_rust.py` のユーザー固有パス除去

- **対象**: `build_rust.py` L138
- **問題**: `env["PATH"] = r"C:\Users\aokuni\.cargo\bin;" + env.get("PATH", "")` がマシン固有。他環境・CI で壊れる。
- **修正**:

```python
    cargo_bin = os.path.join(os.path.expanduser("~"), ".cargo", "bin")
    if os.path.isdir(cargo_bin):
        env["PATH"] = cargo_bin + os.pathsep + env.get("PATH", "")
```

- **検証**: `python build_rust.py` がローカルで従来どおり Rust ビルドに到達すること(フルビルドまで回さなくても Step 1 の maturin 呼び出しが通れば可)。

### 1-7. 設定バリデーションテストの CWD 依存解消

- **対象**: `test/test_config_validation_unit.py`
- **問題**: `test_config.yaml` を CWD に書き、`template_feb: "template2.feb"` の解決も CWD 依存のため、vexis ルート以外から pytest を実行すると `test_analysis_num_threads_valid` が `FileNotFoundError` で失敗する(検証済み)。
- **修正**:
  1. `setUp` で `tempfile.mkdtemp()`(または `tempfile.TemporaryDirectory`)を使い、YAML はその中に書く。`tearDown` で後始末。
  2. `template_feb` にはリポジトリルートの実物を絶対パスで渡す:

```python
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATE = os.path.join(REPO_ROOT, "template2.feb")
# 各テストの data 中: "template_feb": TEMPLATE
```

- **検証**: vexis ルート以外のディレクトリ(例: `C:\`)から `python -m pytest <絶対パス>/test <絶対パス>/tests --rootdir=<絶対パス>` を実行して全件成功すること。

---

## Phase 2: Rust/Vulkan デプロイ準備

### 2-1. `test_binding.py` を現行 API に更新し、手動スクリプトとして再配置

- **対象**: `src/libs/vexis_vulkan_core/test_binding.py`
- **問題**:
  1. `renderer.render_mesh(flat_coords, values, indices, mvp, min_val, max_val)` と 6 引数で呼んでいるが、現行 Rust API(`renderer.rs` L455, L512)は `set_mesh(positions, indices)` + `render_mesh(values, mvp_matrix, min_val, max_val)` の 2 段階。実行しても動かない。
  2. `.xplt` パスが `c:\github_repo\vexis\temp\example_1.xplt` にハードコード。
  3. `test_*.py` 名のため素の `pytest` 実行で収集される。
- **修正**:
  1. ファイル名を `manual_check_binding.py` に変更(git mv)。
  2. レンダリング部を現行 API に更新:

```python
        renderer = vexis_vulkan_core.VulkanRenderer(1920, 1080)
        renderer.set_mesh(flat_coords, indices)
        frame = renderer.render_mesh(values, mvp, float(min_val), float(max_val))
```

  3. 対象ファイルを引数化: `target_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "..", "temp", "example_1.xplt")` のようにリポジトリ相対のデフォルト+引数上書きにする。
- **検証**: `temp/example_1.xplt` が存在する環境で `python manual_check_binding.py` が最後まで走り `vulkan_contour_test.png` を出力すること(ファイルが無い環境ではエラーメッセージ表示のみで可)。

### 2-2. `test_matplotlib.py` の壊れたパス依存を修正し再配置

- **対象**: `src/libs/vexis_vulkan_core/test_matplotlib.py`
- **問題**: 削除済み worktree(`worktrees/vexis-rust-vulkan/...`)を `sys.path.append` しており動作不能。`test_*.py` 名のため素の pytest で collection エラーの原因になる。
- **修正**:
  1. ファイル名を `manual_check_matplotlib.py` に変更(git mv)。
  2. L5-7 の `sys.path.append(r"c:\github_repo\vexis\worktrees\...")` を削除(maturin develop 済み環境なら `import vexis_vulkan_core` は素で通る)。
  3. 2-1 と同様に `.xplt` パスを引数化。
- **検証**: 2-1 と同様。

### 2-3. pytest 収集対象から Rust ライブラリフォルダを除外

- **対象**: `pytest.ini`
- **修正**: `norecursedirs` に `src/libs/vexis_vulkan_core` を追加する。

```ini
norecursedirs = .git .venv .pdfenv build dist worktrees src/libs/waffleiron/test src/libs/vexis_vulkan_core
```

- **補足**: 2-1/2-2 のリネーム後は実害がなくなるが、今後同フォルダに置かれるスクリプトの事故防止として入れておく。
- **検証**: vexis ルートで引数なしの `python -m pytest` を実行し、collection エラーが出ないこと。

### 2-4. `vulkan_widget.py` の import を遅延化(GUI 統合前の安全策)

- **対象**: `src/gui/panels/vulkan_widget.py` L6
- **問題**: モジュール先頭の `import vexis_vulkan_core` のため、将来 GUI に接続した時点でネイティブモジュール不在の環境では起動ごと落ちる。
- **修正**: `src/gui/panels/mesh_preview.py` の `_ensure_pyvista()` と同じパターンで遅延 import 化する。

```python
VULKAN_AVAILABLE = False
vexis_vulkan_core = None


def _ensure_vulkan_core():
    global VULKAN_AVAILABLE, vexis_vulkan_core
    if vexis_vulkan_core is None:
        try:
            import vexis_vulkan_core as _core
            vexis_vulkan_core = _core
            VULKAN_AVAILABLE = True
        except ImportError:
            VULKAN_AVAILABLE = False
    return VULKAN_AVAILABLE
```

`VulkanImageWidget.resizeEvent()` 内で `VulkanRenderer` を生成する直前に `_ensure_vulkan_core()` を呼び、False の場合は `image_label` に「Vulkan renderer not available」を表示して return する。

- **検証**: `python -c "from src.gui.panels import vulkan_widget"` がネイティブモジュールの有無に関わらず成功すること。

### 2-5. 旧 `build.py` の退役

- **対象**: `build.py`
- **問題**: 参照する `VEXIS-CAE.spec` は既に `obsolute/packaging_artifacts/` へ退避済みで、実行すると PyInstaller が必ず失敗する。パッケージングは `build_rust.py` に一本化される。
- **修正**: `build.py` を `obsolute/packaging_artifacts/build.py` へ移動する(git 追跡から外れる)。`README.md` / `doc/Development_Guide.md` に `build.py` への言及があれば `build_rust.py` に書き換える。
- **検証**: リポジトリルートに `build.py` が無いこと。grep で参照が残っていないこと。

---

## Phase 3: デッドコード削除(挙動不変)

いずれも 2026-07-02 時点で **grep により呼び出しゼロを確認済み**。削除前に念のため `Grep` で再確認してから消すこと。

### 3-1. `src/mesh_gen/utils.py` の未使用 3 関数

- `permute_xyz()`(L32-42。`main.py` はインラインで置換済み)
- `snap_interface_nodes_core_to_ring()`(L162-204。`snap_interface_nodes_by_theta_layers` に置き換え済み)
- `_merge_duplicate_points_with_backoff()`(L413-433)
- あわせて `src/mesh_gen/main.py` L182 の宙に浮いたコメント `# Merge duplicates robustly (avoid creating degenerate cells by over-rounding)` を削除。
- 不要になった import(`cKDTree` は `snap_interface_nodes_by_theta_layers` 側で未使用になるか確認)を整理。

### 3-2. `src/mesh_gen/core_mesh.py`

- `_enforce_outer_arc_nodes()`(L8-37)を削除。
- `extrude_core_to_3d()` の未使用引数 `revolve_angle_deg: float = 90.0`(L235)をシグネチャから削除(呼び出し元 `main.py` は渡していないため影響なし)。

### 3-3. `src/utils/geometry.py` の未使用 2 関数

- `tfi_blend()`(L213-242)を削除。同ロジックは `core_mesh.py` L135-152 にインラインで存在し、そちらが実際に使われている(インライン側は変更しない)。
- `get_absolute_coordinates()`(L47-62)を削除。
- **注意**: `tests/test_refactor_regressions.py` の re-export テストは上記 2 関数を要求リストに含んでいないため影響しないが、削除後にテストを実行して確認すること。

### 3-4. `src/mesh_gen/config.py`

- `merge_decimals` フィールド(L17)と `from_yaml` 内の読み込み(L46)を削除(唯一の消費者だった 3-1 のマージ関数がデッドのため。`config/config.yaml` に同キーは存在しない)。
- `radial_mapping_beta` のコメント(L16)を修正。現状の `# currently unused (kept for forward compatibility)` は**誤り**(実際は `main.py` L139 → `core_mesh.py` の `_eta()` で径方向ノード分布の指数として使用中)。以下に変更:

```python
    radial_mapping_beta: float = 2.0  # O-grid 径方向のノード分布指数(>1 で外周寄りに密集)
```

### 3-5. `src/mesh_swap/mesh_replacer.py` のデッドブロック 4 箇所

1. L173-217: 無効化済み Auto-Align のコメントアウト約 45 行(`# Auto-Align: ...` から `#         print(f"Warning: Failed to align mesh: {e}")` まで)を削除。git 履歴に残っているため復元可能。先頭の 2 行コメント(`[DISABLED] 2024-12-18: Causing harmful center offset...`)は経緯として価値があるため、削除するコード位置に 1 行だけ残してよい。
2. L219-228: `invert_hex8 = False` で永久に実行されない反転ハック(`# FIX: Invert Elements ...` ブロック全体)を削除。
3. L41-46: 未使用の `_set_xml_tail()` を削除。
4. L640-645: `override_rigid_bc()` 内の何もしない分岐(`if target_bc.get("type") == "rigid_fixed": ... pass`)とその周辺の思考メモコメント(L629-634)を削除。

### 3-6. `src/gui/models/job_item.py`

- `JobStatus.MESHING`(L7)を削除(どのコードパスもこの状態を設定しない)。`display_status()` のマップから対応エントリも削除。

### 3-7. `analysis_helpers.py` L157

- コメントアウトの `# os.makedirs(os.path.dirname(os.path.abspath(GLOBAL_LOG_PATH)), exist_ok=True)` を削除(`GLOBAL_LOG_PATH` という変数自体が存在しない)。

### 3-8. `gui_main.py` のコメントアウト残骸

- コメントアウトされた `print` / `logger` 行(L97, L99-100, L109, L123, L129-130, L166-167, L171, L184-185, L205-206 付近)を削除。動作コメント(処理意図の説明)は残す。

- **Phase 3 全体の検証**: `python -m pytest test tests` 全件成功、`python gui_main.py` 起動確認、`python main.py --mesh-only` 成功。

---

## Phase 4: ファイル・テスト整理

### 4-1. `test/patent.md` の移動

- 特許文書(約 23KB)がテストフォルダにあるのは迷子。`paper/patent.md` へ git mv する。

### 4-2. `test/measure_codebase.py` の移動

- テストではなくコードベース計測スクリプト。`tools/measure_codebase.py` へ git mv する。
- 移動後、スクリプト冒頭の `ROOT_DIR = SCRIPT_DIR.parent` が引き続きリポジトリルートを指すことを確認(`tools/` 直下なら `parent` で正しい)。

### 4-3. `generate_adaptor_sample.py` の退避

- `pyfebio`(requirements.txt に無い)を使う一回きりの実験スクリプト。`obsolute/` へ移動する。

### 4-4. `profiler.py` の移動と引数化

- `tools/profiler.py` へ git mv する。
- ハードコードパス `r"c:\github_repo\vexis\temp\example_1.xplt"` を `sys.argv[1]` 優先+リポジトリ相対デフォルトに変更(2-1 と同じ方式)。
- 移動により `from src.utils.xplt_loader import WaffleironLoader` が CWD 依存になるため、スクリプト冒頭でリポジトリルートを `sys.path` に追加する:

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

### 4-5. `test/` と `tests/` の統合

- **方針**: `tests/` に一本化する(Python 慣習)。
- 手順:
  1. `test/test_config_validation_unit.py` を `tests/` へ git mv(1-7 の修正済みの状態で)。
  2. `test/` フォルダを削除(4-1, 4-2 の移動後は `__pycache__` しか残らないはず)。
  3. `tests/` が **git 未追跡**のままなので、`tests/` 全体を `git add` する。
  4. `AGENTS.md` の検証コマンドを `python -m pytest test tests` から `python -m pytest tests` に更新。
  5. `pytest.ini` に変更は不要(`python_files = test_*.py` のまま)。
- **検証**: vexis ルートで `python -m pytest tests` 全件成功。

### 4-6. `requirements.txt` の UTF-8 化とピン留め

- **問題**: 現状 UTF-16 LE(BOM 付き)で保存されている。pip は BOM 検出で動くが、grep 等の他ツールで化ける。また末尾 3 行(`art`, `watchdog`, `pyvistaqt`)だけバージョン未ピン。
- **修正**:
  1. ファイルを UTF-8(BOM なし)で書き直す。内容(パッケージと版)は変えない。
  2. `.venv` の実際のインストール版で末尾 3 つをピン留めする:

```powershell
.\.venv\Scripts\python.exe -m pip show art watchdog pyvistaqt | Select-String "Name|Version"
```

  で版を確認し、`art==X.Y.Z` 形式に書き換える。
- **注意**: freeze 出力を直接依存だけに絞る整理は**今回はやらない**(保留項目参照)。
- **検証**: `python -m pip install -r requirements.txt --dry-run` がエラーなく解決すること。

---

## Phase 5: 低リスク品質改善

### 5-1. `_to_scalar_magnitude` の重複統合

- **対象**: `src/gui/panels/result_viewer.py`(`ScalarRangeThread._to_scalar_magnitude` L59-68 と `ResultViewer._to_scalar_magnitude` L715-724 が同一実装)
- **修正**: モジュールレベルの関数 `_to_scalar_magnitude(values)` に一本化し、両クラスから呼ぶ。挙動は変えない。

### 5-2. `filter_nodes_by_relative_bounds` のベクトル化

- **対象**: `src/utils/geometry.py` L113-145
- **問題**: Python ループで 1 ノードずつ処理しており、数万ノード×セット数で遅い(セット再構築のホットパス)。
- **修正**: 挙動を厳密に維持したまま NumPy 化する。ゼロ幅次元の扱い(`extent == 0` → `np.inf` 除算で相対座標 0)も現行と一致させること。

```python
    nodes = np.asarray(nodes, dtype=float)
    rel_min, rel_max = relative_bounds
    rel_min = np.asarray(rel_min, dtype=float)
    rel_max = np.asarray(rel_max, dtype=float)

    tol = 0.05
    rel_min_tol = np.maximum(rel_min - tol, 0.0)
    rel_max_tol = np.minimum(rel_max + tol, 1.0)

    min_c, max_c = global_bbox
    extent = np.asarray(max_c, dtype=float) - np.asarray(min_c, dtype=float)
    safe_extent = np.where(extent == 0, np.inf, extent)
    rel = (nodes - np.asarray(min_c, dtype=float)) / safe_extent

    mask = np.all(rel >= rel_min_tol, axis=1) & np.all(rel <= rel_max_tol, axis=1)
    return np.where(mask)[0].astype(int)
```

- **検証**: 既存テスト(re-export テスト)+ `tests/` に小さな一致テストを追加してもよい(旧実装と同じ入力で同じ index 集合が返ること)。

### 5-3. `extract_results.py` の docstring 修正

- **対象**: `src/mesh_swap/result_analysis/extract_results.py` L7-17
- **問題**: docstring の戻り値列挙に `RB_ID` 列が抜けている(実際の DataFrame は `['Time', 'RB_ID', 'Disp_Z', 'Force_Z', 'Stroke', 'Reaction_Force']`)。
- **修正**: docstring を実装に合わせる。コードは変更しない。

---

## 保留項目(Codex は触らないこと・ユーザー判断待ち)

| `項目` | `内容` | `保留理由` |
| :--- | :--- | :--- |
| `plugins/advanced_mesher/` | `どこからも参照されていない実験コード` | `plugins/Development_plan_mesh_gen_FElupe.md と関連する将来計画の可能性があるため` |
| `renderer.rs の render_frame()` | `Python 側から未使用の API` | `Vulkan 統合計画の一部かもしれないため Rust 側の判断が必要` |
| `QThread.terminate() の廃止` | `result_viewer.py で強制終了を使用(状態破損リスク)` | `協調的停止への変更は挙動変更を伴うため別タスク` |
| `mesh_preview.py の非同期化` | `STEP→プレビュー変換が GUI スレッドで同期実行(大きい STEP でフリーズ)` | `UX 改善であり挙動変更を伴うため別タスク` |
| `requirements.txt の直接依存への絞り込み` | `現状は transitive 込みの freeze 出力` | `依存解決の変化リスクがあるため別タスク` |
| `cleanup_orphans の設計見直し` | `1-5 のガードで実害は塞がるが、削除→再構築の順序自体はテンプレート構造依存` | `大規模リファクタになるため。1-5 で十分` |

---

## 完了チェックリスト

- [ ] Phase 1: 7 項目すべて実施、回帰テスト(1-5)追加済み
- [ ] Phase 2: 5 項目すべて実施、`maturin develop` + import 確認済み
- [ ] Phase 3: 8 項目すべて実施(削除前に grep で呼び出しゼロを再確認)
- [ ] Phase 4: 6 項目すべて実施、`tests/` が git 追跡下にある
- [ ] Phase 5: 3 項目すべて実施
- [ ] vexis ルートで `python -m pytest tests` 全件成功
- [ ] vexis ルート**以外**から pytest を実行しても成功(1-7 の確認)
- [ ] 引数なし `python -m pytest` で collection エラーなし(2-3 の確認)
- [ ] `python gui_main.py` 起動確認
- [ ] `python main.py --mesh-only` 成功(input/ に STEP がある場合)
- [ ] Phase 単位でコミット済み(`.agent/workflows/commit.md` 準拠)
- [ ] `dev_log/work_summary_YYYYMMDD.md` に作業サマリ追記済み
