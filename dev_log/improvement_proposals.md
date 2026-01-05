# VEXIS-CAE 高優先度項目 調査報告・改善提案

## 1. ランタイム依存関係のパッケージ化改善

### 現状の問題

#### 発生した現象
- 開発環境（Python直接実行）で同梱ソルバー `solver/febio4.exe` を呼び出すと、終了コード `3221225781` (`0xC0000135 = STATUS_DLL_NOT_FOUND`) でクラッシュする。
- PyInstaller でビルドした EXE 版では問題なく動作する。

#### 原因分析
現在の `VEXIS-CAE.spec` では以下のように `solver` ディレクトリを **datas** として同梱している：
```python
datas=[('solver', 'solver')]
```

`solver/` に含まれるファイル：
| ファイル名            | サイズ | 備考                              |
| --------------------- | ------ | --------------------------------- |
| `febio4.exe`          | 73KB   | メインソルバー本体 (薄いラッパー) |
| `febiolib.dll`        | 850KB  | FEBio コアライブラリ              |
| `fecore.dll`          | 2MB    | FEBio コア                        |
| `numcore.dll`         | 116MB  | 数値計算コア (MKL/OpenMP 依存)    |
| `libiomp5md.dll`      | 1.9MB  | Intel OpenMP ランタイム           |
| `libcrypto-3-x64.dll` | 4.6MB  | OpenSSL                           |
| `libssl-3-x64.dll`    | 800KB  | OpenSSL                           |
| `zlib1.dll`           | 87KB   | 圧縮ライブラリ                    |

**問題点：** 上記の DLL は同梱されているが、**Visual C++ 再頒布可能パッケージ (CRT DLL)** である `msvcp140.dll`、`vcruntime140.dll`、`vcruntime140_1.dll` 等が含まれていない。PyInstaller ビルドでは Python 自体が依存する VC++ ランタイムも一緒に同梱されるため問題になりにくいが、開発環境ではシステムにインストールされていない場合がある。

### 改善案

#### A. VC++ ランタイム DLL を `solver/` に同梱する
FEBio Studio のインストールディレクトリ (`C:\Program Files\FEBioStudio\bin\`) から必要な DLL をコピーするか、[Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) からダウンロードした DLL を `solver/` に直接配置する。

**対象 DLL 候補：**
- `msvcp140.dll`
- `vcruntime140.dll`
- `vcruntime140_1.dll`
- `msvcp140_1.dll` (必要に応じて)

#### B. PyInstaller spec で `binaries` に明示追加する
```python
binaries = [
    ('C:/Windows/System32/msvcp140.dll', 'solver'),
    ('C:/Windows/System32/vcruntime140.dll', 'solver'),
    ('C:/Windows/System32/vcruntime140_1.dll', 'solver'),
]
```

#### C. フォールバック機構の強化（現行対応）
現在 `analysis_helpers.py` には、同梱ソルバーが DLL エラーで起動失敗した場合にシステムインストール版 FEBio にフォールバックするロジックが実装済み。ただし、これは根本解決ではなく緊急回避策であり、ユーザー環境に FEBio Studio がインストールされていない場合は依然として失敗する。

#### 推奨アクション
1. **短期**: FEBio Studio インストールディレクトリから必要な CRT DLL を `solver/` にコピーして同梱する。
2. **中期**: `.spec` ファイルで `binaries` に明示追加し、ビルドプロセスを自動化する。
3. **長期**: 静的リンク版の FEBio ソルバーを構築するか、公式の再配布可能バイナリを使用する。

---

## 2. ポストプロセッサ (3D Result Viewer) の高速化

### 現状の問題

#### 発生した現象
- `3D Result` タブでタイムステップスライダーを操作すると、マウスの動きに追従せず 2〜3 秒遅れてコンター画像が更新される。
- 特にメッシュが大きい場合（数千〜数万要素）に顕著。

#### 原因分析
`result_viewer.py` のデータフローを分析した結果、以下のボトルネックを特定：

```
スライダー操作 → set_step() → _load_mesh_file() → _display_mesh()
```

| 処理                       | コスト     | 備考                           |
| -------------------------- | ---------- | ------------------------------ |
| `pv.read()`                | 低         | キャッシュ済み (`_mesh_cache`) |
| `mesh.warp_by_vector()`    | **高**     | 毎回新しい変形メッシュを生成   |
| `mesh.linear_copy()`       | **高**     | 2次要素を1次要素に変換         |
| `mesh.extract_all_edges()` | **中〜高** | エッジ抽出                     |
| `plotter.add_mesh()`       | 中         | レンダリングパイプライン       |

**問題点：**
1. **`warp_by_vector` が毎ステップ再計算されている**：同じメッシュトポロジで変位ベクトルだけが異なる場合でも、新しい PyVista メッシュオブジェクトを毎回生成している。
2. **`linear_copy` と `extract_all_edges` も毎回実行**：エッジ表示用の処理が重複。
3. **キャッシュが不完全**：`_mesh_cache` は VTK ファイル読み込み結果のみをキャッシュしており、ワープ後のメッシュやエッジはキャッシュされていない。

### 改善案

#### A. ワープ後メッシュのキャッシュ
```python
# 既存の _mesh_cache に加えて、ワープ済みメッシュをキャッシュ
self._warped_cache = {}

def _load_mesh_file(self, file_path, ...):
    if file_path in self._warped_cache:
        self.warped_mesh = self._warped_cache[file_path]
    else:
        raw = self._mesh_cache.get(file_path) or pv.read(file_path)
        self.warped_mesh = raw.warp_by_vector("displacement") if "displacement" in raw.point_data else raw
        self._warped_cache[file_path] = self.warped_mesh
```

#### B. エッジ抽出結果のキャッシュ
```python
self._edge_cache = {}

def _get_edges(self, mesh, file_path):
    if file_path in self._edge_cache:
        return self._edge_cache[file_path]
    edge_mesh = mesh.linear_copy() if hasattr(mesh, 'linear_copy') else mesh
    edges = edge_mesh.extract_all_edges()
    self._edge_cache[file_path] = edges
    return edges
```

#### C. スライダー操作のデバウンス
スライダーを高速でドラッグした場合、すべてのステップを描画せず、最終位置のみを描画する。

```python
from PySide6.QtCore import QTimer

self._slider_timer = QTimer()
self._slider_timer.setSingleShot(True)
self._slider_timer.timeout.connect(self._do_update_step)

def set_step(self, step_index, force_reset=False):
    self._pending_step = step_index
    self._pending_reset = force_reset
    self._slider_timer.start(100)  # 100ms デバウンス

def _do_update_step(self):
    # 実際の更新処理
    ...
```

#### D. バックグラウンドプリロード
ジョブ選択時にすべての VTK ステップをバックグラウンドスレッドで読み込み・ワープ処理しておく。

```python
from concurrent.futures import ThreadPoolExecutor

def _preload_all_steps(self):
    with ThreadPoolExecutor(max_workers=2) as executor:
        for vtk_path in self.vtk_files:
            executor.submit(self._load_and_cache_step, vtk_path)
```

#### 推奨アクション
1. **短期**: ワープ済みメッシュとエッジのキャッシュを実装（効果大、実装コスト低）
2. **短期**: スライダーにデバウンスを追加（効果中、実装コスト低）
3. **中期**: バックグラウンドプリロード（効果大、実装コスト中）

---

## まとめ

| 項目         | 根本原因                | 推奨対策                     | 実装難易度 |
| ------------ | ----------------------- | ---------------------------- | ---------- |
| DLL 同梱     | CRT ランタイム不足      | `solver/` に VC++ DLL を追加 | 低         |
| VTK 表示遅延 | ワープ/エッジ毎回再計算 | キャッシュ + デバウンス      | 低〜中     |

---
*Last Updated: 2026-01-05*
*Author: Antigravity*
