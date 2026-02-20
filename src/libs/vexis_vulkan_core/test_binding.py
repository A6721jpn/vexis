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
        disp = parser.get_node_data(0, 'displacement')
        stress = parser.get_domain_data(0, 'stress')
        strain = parser.get_domain_data(0, 'Lagrange strain')
        t3 = time.time()
        print(f"Extracted Step 0 Displacement size: {len(disp)} items")
        print(f"Extracted Step 0 Stress size: {len(stress)} items")
        print(f"Extracted Step 0 Strain size: {len(strain)} items")
        print(f"[Timer] Extracting Step 0 variables: {(t3 - t2) * 1000.0:.3f} ms")
        
        try:
            t4 = time.time()
            coords = parser.get_base_coordinates()
            elems = parser.get_domain_elements(0)
            t5 = time.time()
            print(f"Extracted Base Coordinates size: {len(coords)} nodes")
            print(f"Extracted Domain 0 Elements list size: {len(elems)} ints")
            print(f"[Timer] Extracting Mesh Geometry: {(t5 - t4) * 1000.0:.3f} ms")
        except Exception as e:
            print(f"Mesh Extraction Failed: {e}")
            parser.dump_structure()

    # Test Renderer
    renderer = vexis_vulkan_core.VulkanRenderer(800, 600)
    frame = renderer.render_frame([1.0, 0.0, 0.0, 0.0]) # Dummy matrix
    print(f"Renderer returned frame buffer of size: {len(frame)} bytes")

except Exception as e:
    print(f"Error testing vexis_vulkan_core: {e}")
