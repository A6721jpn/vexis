import sys
import time

try:
    import vexis_vulkan_core
    print("vexis_vulkan_core successfully imported!")

    target_file = r"c:\github_repo\vexis\temp\example_1.xplt"
    
    t0 = time.time()
    # Test Parser (Mmap load & basic scan)
    parser = vexis_vulkan_core.XpltFastParser(target_file)
    t1 = time.time()
    
    print(f"Parser returned: {parser.get_num_nodes()} nodes, {parser.get_num_elements()} elements")
    print(f"Parser found: {parser.get_num_steps()} steps")
    # parser.dump_structure() # Debug
    
    print(f"Node Vars: {parser.get_node_vars()}")
    print(f"Domain Vars: {parser.get_domain_vars()}")
    print(f"[Timer] Rust Mmap & Basic Scan: {(t1 - t0) * 1000.0:.3f} ms")
    
    if parser.get_num_steps() > 0:
        t2 = time.time()
        last_step = parser.get_num_steps() - 1
        disp = parser.get_node_data(last_step, 'displacement')
        stress = parser.get_domain_data(last_step, 'stress')
        strain = parser.get_domain_data(last_step, 'Lagrange strain')
        t3 = time.time()
        print(f"Extracted Step 0 Displacement size: {len(disp)} items")
        print(f"Extracted Step 0 Stress size: {len(stress)} items")
        print(f"Extracted Step 0 Strain size: {len(strain)} items")
        print(f"[Timer] Extracting Step 0 variables: {(t3 - t2) * 1000.0:.3f} ms")
        
        try:
            t4 = time.time()
            coords = parser.get_base_coordinates()
            
            elems = []
            d = 0
            while True:
                try:
                    elems.extend(parser.get_domain_elements(d))
                    d += 1
                except Exception:
                    break
                    
            t5 = time.time()
            print(f"Extracted Base Coordinates size: {len(coords)} nodes")
            print(f"Extracted Elements list size from {d} domains: {len(elems)} ints")
            print(f"[Timer] Extracting Mesh Geometry: {(t5 - t4) * 1000.0:.3f} ms")
        except Exception as e:
            print(f"Mesh Extraction Failed: {e}")
            parser.dump_structure()

    # 準備: Rustへ渡すメッシュデータの構築
    import math

    if parser.get_num_steps() > 0:
        # 座標の平坦化
        flat_coords = []
        for c in coords:
            flat_coords.extend(c)

        # スカラー値の算出 (今回は変位の大きさをスカラー値とする)
        values = []
        for d in disp:
            mag = math.sqrt(d[0]**2 + d[1]**2 + d[2]**2)
            values.append(mag)
        
        min_val = min(values) if values else 0.0
        max_val = max(values) if values else 1.0
        if max_val == min_val:
            max_val = min_val + 1.0

        print(f"Sample values (first 10): {values[:10]}")
        print(f"Sample values (last 10): {values[-10:]}")
        print(f"Computed min_val={min_val}, max_val={max_val}")

        # 要素リストから三角形インデックスを作成
        # XPLTは多くの場合1-indexed
        min_idx = min(elems) if elems else 1
        indices = []
        
        # 要素が8節点(Hex)の場合を想定して簡易的にTriangulate
        for i in range(0, len(elems), 8):
            if i + 7 < len(elems):
                # 節点インデックス (0-indexedに変換)
                n = [elems[i+j] - min_idx for j in range(8)]
                
                # 安全対策: 範囲外のインデックスを参照している場合はその要素（おそらくShell等）をスキップ
                if any(idx < 0 or idx >= len(values) for idx in n):
                    continue
                    
                # XPLT/LS-DYNA Hex8 node connectivity:
                # 0,1,2,3 = bottom face (CCW if looked from top, actually 0,1,2,3)
                # 4,5,6,7 = top face
                # 0,1,5,4 = front face
                # 1,2,6,5 = right face
                # 2,3,7,6 = back face
                # 3,0,4,7 = left face
                faces = [
                    (n[0], n[3], n[2]), (n[0], n[2], n[1]), # Bottom (facing -z) - reversed normal
                    (n[4], n[5], n[6]), (n[4], n[6], n[7]), # Top (facing +z)
                    (n[0], n[1], n[5]), (n[0], n[5], n[4]), # Front (facing -y)
                    (n[1], n[2], n[6]), (n[1], n[6], n[5]), # Right (facing +x)
                    (n[2], n[3], n[7]), (n[2], n[7], n[6]), # Back (facing +y)
                    (n[3], n[0], n[4]), (n[3], n[4], n[7])  # Left (facing -x)
                ]
                for f in faces:
                    indices.extend(f)

        referenced_values = [values[i] for i in set(indices)]
        ref_min = min(referenced_values) if referenced_values else 0.0
        ref_max = max(referenced_values) if referenced_values else 1.0
        print(f"Referenced vertices MIN: {ref_min}, MAX: {ref_max}")

        # MVP行列の計算 (簡易的なスケーリングとセンタリング)
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        zs = [c[2] for c in coords]
        min_c = [min(xs), min(ys), min(zs)]
        max_c = [max(xs), max(ys), max(zs)]
        center = [(min_c[i] + max_c[i]) / 2.0 for i in range(3)]
        extent = max([max_c[i] - min_c[i] for i in range(3)])
        scale = 1.8 / extent if extent > 0 else 1.0

        # Vulkanは列優先(Column-Major)メモリ配置
        mvp = [
            [scale, 0.0, 0.0, 0.0],
            [0.0, scale, 0.0, 0.0],
            [0.0, 0.0, 0.01, 0.0],
            [-center[0]*scale, -center[1]*scale, 0.5, 1.0]
        ]

        # Test Renderer
        renderer = vexis_vulkan_core.VulkanRenderer(1920, 1080)
        
        print(f"Calling render_mesh with {len(flat_coords)//3} vertices, {len(indices)//3} triangles...")
        t_render_start = time.time()
        frame = renderer.render_mesh(flat_coords, values, indices, mvp, float(min_val), float(max_val))
        t_render_end = time.time()
        print(f"Renderer returned frame buffer of size: {len(frame)} bytes in {(t_render_end - t_render_start)*1000.0:.3f} ms")
        
        try:
            from PIL import Image
            img = Image.frombytes('RGBA', (1920, 1080), bytes(frame))
            img.save('vulkan_contour_test.png')
            print(f"Rendered contour frame saved to: {sys.path[0]}\\vulkan_contour_test.png")
        except ImportError:
            print("PIL (Pillow) not found. Please install it to save the rendered image: pip install pillow")
        except Exception as e:
            print(f"Failed to save image: {e}")

except Exception as e:
    print(f"Error testing vexis_vulkan_core: {e}")
