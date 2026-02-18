# mesh_gen_experimental

Production (`src/mesh_gen`) を変更せずに、Gmsh/FElupe のメッシュ健全性解析を試すための試作エンジンです。

## 目的

- `singular node ... irregular vertex` 警告を減らす試行
- STEP取り込み時の OCC ヒーリング有効化
- 外周リングの2Dクアッドメッシュは **Quasi-structured Quad Meshing 固定**

## 実装ポイント

- OCCヒーリング（可能な環境で）
  - `removeAllDuplicates`
  - `healShapes`
- 外周メッシュ戦略は単一路線
  - `Mesh.Algorithm=11` (Quasi-structured Quad Meshing)
  - `Recombine + Transfinite` を併用
  - `Mesh.MeshOnlyVisible=1` で outer面のみメッシュ化（非対象面の警告混入を防止）
- `singular node` の face/node 集計と bounding box をログ出力
- 半径分割の再fragmentで straddle 面を減らし、軸近傍面の誤分類を抑制
- コアの軸近傍スイープ安定化として radial layer 数を axis-aware に下限補正
- コア押し出し時の outer 境界判定を厳格化し、内側層の誤吸着を防止
- core の radial beta を axis-aware に補正し、軸付近セルの過粗化を抑制

## 実行例

`vexis` ルートで実行:

```bash
python -m src.mesh_gen_experimental.main config/config_mesh_experimental.yaml input/sample.step -o temp/exp_mesh.vtk
```

既存 `config/config.yaml` でも動作します（`mesh_robust` セクションが無ければデフォルト使用）。

## 注意

- これは試作版で、`vexis/main.py` には未接続です。
- 本番導線への反映前に、警告数/収束率/計算時間のA/B比較が必要です。
