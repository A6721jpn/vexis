# FEBio アダプティブ・リメッシング統合計画

## 概要
`pyfebio`ライブラリの`HexRefineAdaptor`構成パターンに従い、`lxml`でFEBio XMLを直接生成してVEXISにアダプティブ・リメッシング機能を統合する。

## 技術的背景
- **参考**: [pyfebio Adaptive Remeshing Example](https://febiosoftware.github.io/pyfebio/examples.html#adaptive-remeshing)
- **依存関係**: `pyfebio`を依存関係として追加せず、既存の`lxml`で同等のXMLを生成

## 必要なXML構造

```xml
<MeshAdaptor>
  <mesh_adaptor type="hex_refine" elem_set="RUBBER_OBJ">
    <max_iters>1</max_iters>
    <max_elements>10000</max_elements>
    <max_elem_refine>0</max_elem_refine>
    <max_value>0.01</max_value>
    <nnc>8</nnc>
    <nsdim>3</nsdim>
    <criterion type="relative error">
      <error>0.01</error>
      <data type="stress">
        <metric>0</metric>
      </data>
    </criterion>
  </mesh_adaptor>
</MeshAdaptor>
```

また、`<Output>`セクションに以下を追加する必要がある:
```xml
<plotfile type="febio">
  <var type="stress error"/>
</plotfile>
```

## 実装タスク

### 1. `analysis_helpers.py` に新関数を追加
```python
def inject_adaptive_remeshing(tree, element_set="RUBBER_OBJ", max_iters=1, max_elements=10000, error=0.01):
    """
    FEBio XMLにアダプティブ・リメッシング設定を注入する。
    """
    root = tree.getroot()
    
    # MeshAdaptorブロックを作成
    mesh_adaptor_section = ET.SubElement(root, "MeshAdaptor")
    adaptor = ET.SubElement(mesh_adaptor_section, "mesh_adaptor", 
                            type="hex_refine", elem_set=element_set)
    ET.SubElement(adaptor, "max_iters").text = str(max_iters)
    ET.SubElement(adaptor, "max_elements").text = str(max_elements)
    ET.SubElement(adaptor, "max_elem_refine").text = "0"
    ET.SubElement(adaptor, "max_value").text = str(error)
    ET.SubElement(adaptor, "nnc").text = "8"
    ET.SubElement(adaptor, "nsdim").text = "3"
    
    criterion = ET.SubElement(adaptor, "criterion", type="relative error")
    ET.SubElement(criterion, "error").text = str(error)
    data = ET.SubElement(criterion, "data", type="stress")
    ET.SubElement(data, "metric").text = "0"
    
    # Outputセクションにstress errorを追加
    output = root.find("Output")
    if output is None:
        output = ET.SubElement(root, "Output")
    
    plotfile = output.find("plotfile")
    if plotfile is None:
        plotfile = ET.SubElement(output, "plotfile", type="febio")
    
    # stress errorが未登録なら追加
    existing_vars = [v.get("type") for v in plotfile.findall("var")]
    if "stress error" not in existing_vars:
        ET.SubElement(plotfile, "var", type="stress error")
```

### 2. `run_integration` に引数を追加
```python
def run_integration(..., adaptive_remeshing=False):
    # ... existing code ...
    
    if adaptive_remeshing:
        inject_adaptive_remeshing(tree)
    
    save_file(tree, out_feb)
```

### 3. GUI/CLIからオプションで有効化
- `config.yaml`に`adaptive_remeshing: false`を追加
- GUIのジョブ設定ダイアログにチェックボックスを追加（将来）

## 検証手順
1. テストスクリプトで生成XMLの構造を確認
2. FEBioソルバーで実行し`Normal Termination`を確認
3. 結果ビューアで可変トポロジーのメッシュが表示されることを確認（別途対応が必要な可能性あり）

## 注意事項
> **可視化への影響**: アダプティブ・リメッシングはシミュレーション中にメッシュトポロジーを変更するため、`result_viewer.py`と`Waffleiron`ローダーで可変メッシュを正しく処理できるか別途検証が必要。

---
*Created: 2026-01-05*
*Status: 計画段階*
