import lxml.etree as ET
import numpy as np
try:
    from .set_reconstructor import SetReconstructor
    # print("Imported SetReconstructor from relative path")
except ImportError as e1:
    try:
        from mesh_swap_automation.set_reconstructor import SetReconstructor
        # print("Imported SetReconstructor from absolute package path")
    except ImportError as e2:
        try:
            from set_reconstructor import SetReconstructor
            # print("Imported SetReconstructor from global path")
        except ImportError as e3:
            print(f"FAILED to import SetReconstructor. Errors: {e1}, {e2}, {e3}")
            pass

def load_reference(path):
    """Parses the FEBio XML file."""
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(path, parser)
    return tree

def find_available_start_id(tree, count, tag_type="node"):
    """
    Finds a starting ID such that [start, start + count - 1] is available.
    Tries to fit in gaps to keep IDs compact/ordered.
    """
    # Collect all used IDs for this tag type (node or elem)
    if tag_type == "node":
        xpath = "//node"
    else:
        tags = ['elem', 'hex8', 'tet4', 'penta6', 'quad4', 'tri3']
        xpath = " | ".join([f"//Mesh//{t}" for t in tags])
    
    used_ids = set()
    for el in tree.xpath(xpath):
        try:
            used_ids.add(int(el.get("id")))
        except:
            pass
            
    if not used_ids:
        return 1
        
    # Force using max ID + 1 to ensure monotonicity and avoid conflicts
    if not used_ids:
        return 1
        
    return max(used_ids) + 1
    
    """
    sorted_ids = sorted(list(used_ids))
    
    # Check gap before first ID (if it starts > 1)
    # But usually we prioritize packing.
    # Gap check: if sorted_ids[i+1] > sorted_ids[i] + 1 + count
    # Then we can fit 'count' items starting at sorted_ids[i] + 1.
    
    # Check identifying start=1
    if sorted_ids[0] > count:
        return 1
        
    for i in range(len(sorted_ids) - 1):
        current = sorted_ids[i]
        next_val = sorted_ids[i+1]
        gap_size = next_val - current - 1
        if gap_size >= count:
            return current + 1
            
    # If no gap, return max + 1
    return sorted_ids[-1] + 1
    """

def replace_mesh(tree, new_nodes, new_elements, part_name, elem_type="hex8"):
    """
    Replaces nodes and elements for a specific part.
    """
    root = tree.getroot()
    mesh_section = root.find("Mesh")
    if mesh_section is None:
        raise ValueError("No <Mesh> section found in file.")

    # 0. Initialize Set Reconstructor
    try:
        reconstructor = SetReconstructor(tree, part_name)
        print(f"SetReconstructor initialized for {part_name}. Found {len(reconstructor.set_definitions)} sets to preserve.")
    except Exception as e:
        print(f"Warning: Failed to initialize SetReconstructor: {e}")
        reconstructor = None

    # INJECT MISSING SURFACE RULES
    if reconstructor:
       existing_names = set(d["name"] for d in reconstructor.set_definitions)
    
       # Rule 1: Bottom Contact Primary (Bottom face excluding absolute bottom)
       target = "RUBBER_BOTTOM_CONTACTPrimary"
       reconstructor.set_definitions = [d for d in reconstructor.set_definitions if d["name"] != target]
       
       print(f"Enforcing surface definition: {target} (z_down_except_bottom)")
       reconstructor.set_definitions.append({
           "type": "Surface",
           "name": target,
           "strategy": "GeometricRule",
           "rule": "z_down_except_bottom"
       })

       # Rule 2: Top Contact Primary (Top face)
       target_top = "TOP_CONTACTPrimary"
       reconstructor.set_definitions = [d for d in reconstructor.set_definitions if d["name"] != target_top]
       
       print(f"Enforcing surface definition: {target_top} (z_up)")
       reconstructor.set_definitions.append({
           "type": "Surface",
           "name": target_top,
           "strategy": "GeometricRule",
           "rule": "z_up"
       })

    # 1. Find target Nodes section
    target_nodes_node = None
    for nodes_node in mesh_section.findall("Nodes"):
        if nodes_node.get("name") == part_name:
            target_nodes_node = nodes_node
            break
    
    if target_nodes_node is None:
        raise ValueError(f"Could not find <Nodes name='{part_name}'>")

    # Remove old nodes from XML and capture coords for alignment
    old_node_ids = set()
    old_coords = []
    
    for child in list(target_nodes_node):
        try:
            nid = int(child.get("id"))
            old_node_ids.add(nid)
            # Parse coords
            if child.text:
                c = [float(x) for x in child.text.strip().replace('\t','').split(',')]
                old_coords.append(c)
        except: pass
        target_nodes_node.remove(child)
        
    print(f"Removed {len(old_node_ids)} old nodes from {part_name}.")

    # Move target_nodes_node to the correct position (After last Nodes, before Elements/Surfaces)
    mesh_section.remove(target_nodes_node)
    
    # helper to find insertion index
    def find_insert_index(parent, tag_priority):
        # Tags order: Nodes, Elements, NodeSet, Surface, ElementSet, ...
        # We want to insert 'tag_priority' (e.g. Nodes) after existing ones of same type,
        # or before any type that comes 'after' it in priority.
        order = ["Nodes", "Elements", "NodeSet", "Surface", "ElementSet", "DiscreteSet", "SurfacePair"]
        
        try:
            my_rank = order.index(tag_priority)
        except ValueError:
            return len(parent) # Append if unknown
            
        insert_idx = 0
        for i, child in enumerate(parent):
            if child.tag in order:
                child_rank = order.index(child.tag)
                if child_rank <= my_rank:
                    insert_idx = i + 1
                else:
                    # Found a tag that comes *after*. Insert here.
                    return i # Insert *before* this child
            else:
                # Unknown tag (e.g. comment), skip or treat as after?
                pass
                
        return insert_idx

    # Insert Nodes
    node_idx = find_insert_index(mesh_section, "Nodes")
    mesh_section.insert(node_idx, target_nodes_node)
    print(f"Moved <Nodes name='{part_name}'> to index {node_idx} of <Mesh> section.")
    
    # Auto-Align: Shift new_nodes to match Centroid XY and Base Z of old_nodes
    # [DISABLED] 2024-12-18: Causing harmful center offset when mesh sizes differ.
    # if len(old_coords) > 0 and len(new_nodes) > 0:
    #     try:
    #         old_arr = np.array(old_coords)
    #         new_arr = np.array(new_nodes)
    #         
    #         # Auto-Align: Shift new_nodes to match Min-X, Min-Y, and Min-Z of old_nodes
    #         
    #         # Recompute Min/Max
    #         old_min = np.min(old_arr, axis=0)
    #         new_min = np.min(new_arr, axis=0)
    #         
    #         old_max = np.max(old_arr, axis=0)
    #         
    #         # Align Min coordinates exactly (Bottom-Left-Front corner)
    #         shift_x = old_min[0] - new_min[0]
    #         shift_y = old_min[1] - new_min[1]
    #         shift_z = old_min[2] - new_min[2]
    #         
    #         print(f"Aligning mesh (Min-XYZ): dx={shift_x:.4f}, dy={shift_y:.4f}, dz={shift_z:.4f}")
    #         
    #         # Apply shift to NEW NODES directly
    #         if isinstance(new_nodes, np.ndarray):
    #             new_nodes[:, 0] += shift_x
    #             new_nodes[:, 1] += shift_y
    #             new_nodes[:, 2] += shift_z
    #         else:
    #             # Assume list of lists/tuples
    #             shifted_nodes = []
    #             for node in new_nodes:
    #                 shifted_nodes.append([
    #                     node[0] + shift_x,
    #                     node[1] + shift_y,
    #                     node[2] + shift_z
    #                 ])
    #             new_nodes = shifted_nodes # Update reference used later
    # 
    #         # Check new max Z after shift
    #         new_max_z = np.max(new_arr, axis=0)[2] + shift_z if isinstance(new_nodes, np.ndarray) else max(n[2] for n in new_nodes)
    #         chck_msg = f"New Mesh Max Z after alignment: {new_max_z:.6f} (Old Max Z: {old_max[2]:.6f})\n"
    #         print(chck_msg)
    # 
    #     except Exception as e:
    #         print(f"Warning: Failed to align mesh: {e}")

    # FIX: Invert Elements (Winding) if requested (Hack for Negative Jacobian)
    invert_hex8 = False
    if invert_hex8 and elem_type == "hex8" and len(new_elements) > 0:
        print("Inverting Hex8 elements (Winding Fix)...")
        for i in range(len(new_elements)):
             e = new_elements[i]
             if len(e) == 8:
                 # Permute: 0,1,2,3 -> 0,3,2,1 (Swap 1 and 3)
                 #          4,5,6,7 -> 4,7,6,5 (Swap 5 and 7)
                 new_elements[i] = [e[0], e[3], e[2], e[1], e[4], e[7], e[6], e[5]]

    # 3. Find target Elements section
    target_elems_node = None
    # Try finding by name first
    for elems_node in mesh_section.findall("Elements"):
        if elems_node.get("name") == part_name:
            target_elems_node = elems_node
            break
            
    if target_elems_node is None:
        # Strategy: Iterate all Element blocks, check if they reference the old_node_ids.
        for elems_node in mesh_section.findall("Elements"):
            is_match = False
            for child in elems_node.iter():
                 if child.text:
                     try:
                         ids = [int(x) for x in child.text.replace(',',' ').split()]
                         if any(nid in old_node_ids for nid in ids):
                             is_match = True
                             break
                     except:
                         pass
            if is_match:
                target_elems_node = elems_node
                print(f"Found related Element block: name='{elems_node.get('name')}', type='{elems_node.get('type')}'")
                break
    
    if target_elems_node is not None:
        target_elems_node.set("type", elem_type)
        print(f"Updated Element block type to '{elem_type}'.")
        for child in list(target_elems_node):
            target_elems_node.remove(child)
        print("Removed old elements.")
        
        # Move to correct position
        try:
            mesh_section.remove(target_elems_node)
            elem_idx = find_insert_index(mesh_section, "Elements")
            mesh_section.insert(elem_idx, target_elems_node)
            print(f"Moved Elements block to index {elem_idx} of <Mesh> section.")
        except:
            pass
    else:
        print("Creating new <Elements> block.")
        elem_idx = find_insert_index(mesh_section, "Elements")
        target_elems_node = ET.Element("Elements") # Create detached first
        target_elems_node.set("type", elem_type)
        target_elems_node.set("name", part_name)
        mesh_section.insert(elem_idx, target_elems_node)


    # 4. Calculate new IDs using gap finding
    start_node_id = find_available_start_id(tree, len(new_nodes), "node")
    start_elem_id = find_available_start_id(tree, len(new_elements), "elem")
    
    print(f"Renumbering: Nodes start at {start_node_id}, Elements start at {start_elem_id}")

    # 5. Insert New Nodes
    nodes_mapping = {} # local_idx -> global_id
    if len(new_nodes) > 0:
        target_nodes_node.text = "\n\t\t\t"

    for i, node in enumerate(new_nodes):
        global_id = start_node_id + i
        nodes_mapping[i] = global_id
        
        node_elem = ET.SubElement(target_nodes_node, "node")
        x,y,z = node
        node_elem.text = f"{x:e},{y:e},{z:e}"
        node_elem.set("id", str(global_id))
        node_elem.tail = "\n\t\t\t"
    
    if len(target_nodes_node) > 0:
        target_nodes_node[-1].tail = "\n\t\t"

    # 6. Insert New Elements
    if len(new_elements) > 0:
        target_elems_node.text = "\n\t\t\t"

    for i, connectivity in enumerate(new_elements):
        global_eid = start_elem_id + i
        
        elem_elem = ET.SubElement(target_elems_node, "elem")
        elem_elem.set("id", str(global_eid))
        
        # Convert local node indices to global IDs
        global_node_ids = [nodes_mapping[idx] for idx in connectivity]
        
        elem_elem.text = ",".join(map(str, global_node_ids))
        elem_elem.tail = "\n\t\t\t"

    if len(target_elems_node) > 0:
        target_elems_node[-1].tail = "\n\t\t"

    # 7. Reconstruct Sets (NodeSets, Surfaces)
    if reconstructor:
        print("Reconstructing sets...")
        try:
            new_nodes_arr = np.array(new_nodes)
            reconstructed_data = reconstructor.reconstruct(new_nodes_arr, new_elements)
            
            # Update XML NodeSets
            for name, node_indices in reconstructed_data.get("NodeSet", {}).items():
                target_set = None
                for ns in mesh_section.findall("NodeSet"):
                    if ns.get("name") == name:
                        target_set = ns
                        break
                
                if target_set is None:
                    print(f"Creating new NodeSet: {name}")
                    target_set = ET.SubElement(mesh_section, "NodeSet")
                    target_set.set("name", name)
                else:
                    for child in list(target_set):
                        target_set.remove(child)
                
                if node_indices:
                    target_set.text = "\n\t\t\t"
                    for i, n_idx in enumerate(node_indices):
                        if n_idx in nodes_mapping:
                            gid = nodes_mapping[n_idx]
                            n_elem = ET.SubElement(target_set, "node")
                            n_elem.set("id", str(gid))
                            n_elem.tail = "\n\t\t\t"
                    if len(target_set) > 0:
                        target_set[-1].tail = "\n\t\t"
                        
            # Surfaces
            
            surface_elem_start = start_elem_id + len(new_elements)
            current_surf_id = surface_elem_start
            
            for name, faces in reconstructed_data.get("Surface", {}).items():
                 target_surf = None
                 for s in mesh_section.findall("Surface"):
                    if s.get("name") == name:
                        target_surf = s
                        break
                 
                 if target_surf is None:
                     print(f"Creating new Surface: {name}")
                     target_surf = ET.SubElement(mesh_section, "Surface")
                     target_surf.set("name", name)
                 else:
                     for child in list(target_surf):
                         target_surf.remove(child)
                 
                 if faces:
                     target_surf.text = "\n\t\t\t"
                     for face_conn in faces:
                         try:
                             global_nids = [str(nodes_mapping[i]) for i in face_conn]
                         except KeyError:
                             continue
                         
                         
                         count = len(global_nids)
                         if count == 4:
                             tag = "quad4"
                         elif count == 3:
                             tag = "tri3"
                         elif count == 8:
                             tag = "quad8"
                         elif count == 6:
                             tag = "tri6"
                         else:
                             # Fallback or error?
                             tag = "quad4" 
                         
                         se = ET.SubElement(target_surf, tag)
                         se.set("id", str(current_surf_id))
                         se.text = ",".join(global_nids)
                         se.tail = "\n\t\t\t"
                         current_surf_id += 1
                     if len(target_surf) > 0:
                         target_surf[-1].tail = "\n\t\t"
                         
            print(f"Reconstructed {len(reconstructed_data.get('NodeSet',{}))} NodeSets and {len(reconstructed_data.get('Surface',{}))} Surfaces.")

        except Exception as e:
            print(f"Error during set reconstruction: {e}")
            import traceback
            traceback.print_exc()

    # 8. CLEANUP ORPHANS
    cleanup_orphans(tree, old_node_ids)

    # Get max Z for adjustment
    if isinstance(new_nodes, np.ndarray):
        new_max_z = np.max(new_nodes, axis=0)[2]
    else:
        new_max_z = max(n[2] for n in new_nodes) if new_nodes else 0.0

    return nodes_mapping, new_max_z

def cleanup_orphans(tree, deleted_node_ids):
    """
    Removes NodeSets, Surfaces, and ElementSets that reference deleted IDs.
    Also removes Boundary, Contact, Load, etc. that reference the removed Sets.
    """
    root = tree.getroot()
    mesh = root.find("Mesh")
    if mesh is None:
        return

    removed_set_names = set()

    # 1. Check NodeSets
    for nodeset in mesh.findall("NodeSet"):
        should_remove = False
        for n in nodeset.findall("node"):
            try:
                if int(n.get("id")) in deleted_node_ids:
                    should_remove = True
                    break
            except:
                pass
        
        if should_remove:
            name = nodeset.get("name")
            print(f"Removing orphaned NodeSet: {name}")
            removed_set_names.add(name)
            mesh.remove(nodeset)

    # 2. Check Surfaces
    for surface in mesh.findall("Surface"):
        should_remove = False
        for elem in surface:
            if elem.text:
                try:
                    nids = [int(x) for x in elem.text.replace(',', ' ').split()]
                    if any(nid in deleted_node_ids for nid in nids):
                        should_remove = True
                        break
                except:
                    pass
        
        if should_remove:
            name = surface.get("name")
            print(f"Removing orphaned Surface: {name}")
            removed_set_names.add(name)
            mesh.remove(surface)

    # 3. Check SurfacePairs
    for sp in mesh.findall("SurfacePair"):
        should_remove = False
        for child in sp:
            if child.tag in ["primary", "secondary"]:
                if child.text and child.text.strip() in removed_set_names:
                    should_remove = True
                    print(f"SurfacePair '{sp.get('name')}' references removed surface '{child.text.strip()}'")
                    break
        
        if should_remove:
            name = sp.get("name")
            print(f"Removing orphaned SurfacePair: {name}")
            removed_set_names.add(name)
            mesh.remove(sp)

    # 4. Cleanup References
    tags_to_check = ["Boundary", "Loads", "Contact", "Discrete", "Rigid", "Constraints", "MeshAdaptor", "Step"]
    def is_invalid_ref(value):
        if not value: return False
        clean_val = value.replace("@surface:", "")
        return clean_val in removed_set_names

    def clean_element(element):
        children_to_remove = []
        for child in element:
            should_remove_child = False
            for attrib in ["node_set", "surface", "elem_set", "pair", "surface_pair"]:
                val = child.get(attrib)
                if is_invalid_ref(val):
                    should_remove_child = True
                    print(f"Removing invalidated item (attribute ref): tag='{child.tag}', name='{child.get('name')}', invalid_ref='{val}'")
                    break
            
            if not should_remove_child:
                for sub in child:
                    if sub.text and is_invalid_ref(sub.text.strip()):
                         if sub.tag in ["primary", "secondary", "surface", "node_set", "rb"]:
                             should_remove_child = True
                             print(f"Removing invalidated item (child text ref): tag='{child.tag}', name='{child.get('name')}', invalid_ref='{sub.text.strip()}'")
                             break

            if should_remove_child:
                children_to_remove.append(child)
            else:
                clean_element(child)
        
        for child in children_to_remove:
            try:
                element.remove(child)
            except ValueError: pass

    for tag in tags_to_check:
        section = root.find(tag)
        if section is not None:
            clean_element(section) 
            
    for step in root.findall("Step"):
        clean_element(step)

def save_file(tree, output_path):
    # Using pretty_print=False because we manually added newlines
    tree.write(output_path, encoding="ISO-8859-1", xml_declaration=True, pretty_print=False)

def adjust_keycap_height(tree, rubber_max_z, ref_z=2.65):
    """
    Shifts the KEYCAP rigid body nodes to sit on top of the new rubber mesh.
    Shift = (rubber_max_z - ref_z)
    """
    shift_val = rubber_max_z - ref_z
    print(f"Adjusting KEYCAP Z-height: Shift = {shift_val:.6f} (Rubber Top: {rubber_max_z:.6f}, Ref: {ref_z})")
    
    if abs(shift_val) < 1e-6:
        print("Shift is negligible. Skipping.")
        return

    root = tree.getroot()
    mesh = root.find("Mesh")
    
    keycap_nodes = None
    for nodes in mesh.findall("Nodes"):
        if nodes.get("name") in ["KEYCAP", "KEYCAP_OBJ"]:
            keycap_nodes = nodes
            break
            
    if keycap_nodes is None:
        print("Warning: KEYCAP Nodes not found in template. Skipping Z-adjustment.")
        return
        
    count = 0
    for node in keycap_nodes.findall("node"):
        if node.text:
            try:
                coords = [float(x) for x in node.text.strip().replace('\t','').split(',')]
                # Shift Z
                coords[2] += shift_val
                # Write back
                node.text = f"{coords[0]:e},{coords[1]:e},{coords[2]:e}"
                count += 1
            except:
                pass
                
    print(f"Shifted {count} nodes in KEYCAP by {shift_val:.6f}.")

def override_rigid_bc(tree, push_dist):
    """
    Overrides the displacement value for 'KEYCAP_PUSH' rigid constraint.
    """
    if push_dist is None:
        return
        
    print(f"Overriding KEYCAP_PUSH value to: {push_dist}")
    root = tree.getroot()
    
    # Locate <rigid_bc name="KEYCAP_PUSH">
    target_bc = None
    
    # Search within specialized sections or Step
    # Usually in <Boundary> or top level <Rigid>
    # FEBio4 often puts rigid constraints in <Rigid> or <boundary> inside <Step>
    
    # Helper to search recursively
    # ... (end of override_rigid_bc) ...
    for elem in root.iter("rigid_bc"):
        if elem.get("name") == "KEYCAP_PUSH":
            target_bc = elem
            break
            
    if target_bc is not None:
        # Check type
        if target_bc.get("type") == "rigid_fixed":
            # For fixed, we might not have 'value'? 
            # Actually user wants to PUSH. usually type='prescribed_displacement' or rigid_displacement
            pass
        
        # Look for <value> child
        val_node = target_bc.find("value")
        if val_node is not None:
            print(f"Updated KEYCAP_PUSH: {val_node.text} -> {push_dist}")
            val_node.text = str(push_dist)
        else:
             print("Warning: <value> tag not found in KEYCAP_PUSH.")
    else:
        print("Warning: Rigid BC 'KEYCAP_PUSH' not found.")

def override_control_params(tree, time_steps=None):
    """
    Overrides Control parameters like time_steps.
    """
    if time_steps is None:
        return

    print(f"Overriding time_steps to: {time_steps}")
    root = tree.getroot()
    
    # Locate Control. Might be at root or under Step.
    control = root.find("Control")
    if control is None:
        # Search first Step
        step_container = root.find("Step") 
        if step_container is not None:
             # Inside Step container there are <step> elements
             for sub in step_container.findall("step"):
                 c = sub.find("Control")
                 if c is not None:
                     control = c
                     break
    
    if control is None:
        # Try direct search
        control = root.find(".//Control")
        
    if control is None:
        print("Warning: <Control> section not found. Cannot update time_steps.")
        return
        
    # Update time_steps
    ts_node = control.find("time_steps")
    if ts_node is not None:
        print(f"Updated time_steps: {ts_node.text} -> {time_steps}")
        ts_node.text = str(int(time_steps))
    else:
        print("Warning: <time_steps> tag not found in Control. Skipping.")
