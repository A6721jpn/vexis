import sys
import time
import math
import matplotlib.pyplot as plt

sys.path.append(r'c:\github_repo\vexis\worktrees\vexis-rust-vulkan\src\libs\vexis_vulkan_core')
import vexis_vulkan_core

def main():
    parser = vexis_vulkan_core.XpltFastParser(r'c:\github_repo\vexis\temp\example_1.xplt')
    
    if parser.get_num_steps() == 0:
        print("No steps found.")
        return

    last_step = parser.get_num_steps() - 1
    disp = parser.get_node_data(last_step, 'displacement')
    coords = parser.get_base_coordinates()
    
    elems = []
    d = 0
    while True:
        try:
            elems.extend(parser.get_domain_elements(d))
            d += 1
        except Exception:
            break

    # 座標の平坦化配列ではなく、XY座標のみを抽出
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]

    # スカラー値の算出
    values = []
    for d in disp:
        mag = math.sqrt(d[0]**2 + d[1]**2 + d[2]**2)
        values.append(mag)

    min_idx = min(elems) if elems else 1
    indices = []
    
    # test_binding.py と全く同じ Triangulate アルゴリズムを使用
    for i in range(0, len(elems), 8):
        if i + 7 < len(elems):
            n = [elems[i+j] - min_idx for j in range(8)]
            if any(idx < 0 or idx >= len(values) for idx in n):
                continue
            
            # 2D（表面）描画のための手抜きTriangulate (フロント/トップ面等のみ表示、重複はmatplotlibが適当に処理する)
            # Matplotlibのtripcolorに渡すため、全ポリゴンのインデックスリスト (N x 3配列)
            faces = [
                (n[0], n[1], n[2]), (n[0], n[2], n[3]), # Bottom
                (n[4], n[5], n[6]), (n[4], n[6], n[7]), # Top
                (n[0], n[1], n[5]), (n[0], n[5], n[4]), # Front
                (n[1], n[2], n[6]), (n[1], n[6], n[5]), # Right
                (n[2], n[3], n[7]), (n[2], n[7], n[6]), # Back
                (n[3], n[0], n[4]), (n[3], n[4], n[7])  # Left
            ]
            indices.extend(faces)

    print(f"Nodes: {len(xs)}, Triangles: {len(indices)}")

    plt.figure(figsize=(10, 8))
    # cmap=jet is similar to typical CAE contour
    plt.tripcolor(xs, ys, indices, values, shading='gouraud', cmap='jet')
    plt.colorbar(label='Displacement Magnitude')
    plt.title('Matplotlib Contour (Python Reference)')
    plt.axis('equal')
    plt.savefig('matplotlib_contour_test.png', dpi=150)
    print("Saved to matplotlib_contour_test.png")

if __name__ == "__main__":
    main()
