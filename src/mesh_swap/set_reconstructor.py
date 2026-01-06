
import lxml.etree as ET
import numpy as np
from abc import ABC, abstractmethod

try:
    from . import geometry_utils
except ImportError:
    import geometry_utils


# =============================================================================
# Strategy Pattern for Set Reconstruction
# =============================================================================

class ReconstructionStrategy(ABC):
    """Base class for set reconstruction strategies."""
    
    @abstractmethod
    def select_faces(self, definition, boundary_faces, centroids, nodes, bbox):
        """
        Select faces based on the strategy.
        
        Args:
            definition: Dict with strategy-specific parameters
            boundary_faces: List of face tuples (node indices)
            centroids: Array of face centroids (N, 3)
            nodes: Array of new node coordinates  
            bbox: Bounding box tuple (min, max)
            
        Returns:
            List of selected face tuples
        """
        pass


class RelativeBoundsStrategy(ReconstructionStrategy):
    """Strategy A: Filter faces by relative bounds within bounding box."""
    
    def select_faces(self, definition, boundary_faces, centroids, nodes, bbox):
        rel_bounds = definition.get("relative_bounds", ((0,0,0), (1,1,1)))
        valid_indices = geometry_utils.filter_nodes_by_relative_bounds(
            centroids, rel_bounds, bbox
        )
        return [boundary_faces[i] for i in valid_indices]


class ProximityStrategy(ReconstructionStrategy):
    """Strategy B: Filter faces by proximity to partner surface."""
    
    def select_faces(self, definition, boundary_faces, centroids, nodes, bbox):
        partner_centroids = definition.get("partner_centroids")
        if partner_centroids is None or len(partner_centroids) == 0:
            return []
        
        partner_tree = geometry_utils.build_kdtree(partner_centroids)
        dists, _ = geometry_utils.query_kdtree_distance(partner_tree, centroids)
        
        # Tolerance: 5% of bounding box diagonal
        diag = np.linalg.norm(bbox[1] - bbox[0])
        tolerance = diag * 0.05
        
        valid_indices = np.where(dists < tolerance)[0]
        return [boundary_faces[i] for i in valid_indices]


class GeometricRuleStrategy(ReconstructionStrategy):
    """Strategy for geometric rules (z_up, z_down, bbox_bottom, etc.)."""
    
    def select_faces(self, definition, boundary_faces, centroids, nodes, bbox):
        rule = definition.get("rule", "")
        diag = np.linalg.norm(bbox[1] - bbox[0])
        tol = diag * 0.02
        min_z = bbox[0][2]
        
        selected = []
        
        if rule == "bbox_bottom":
            z_coords = centroids[:, 2]
            valid_indices = np.where(z_coords < (min_z + tol))[0]
            selected = [boundary_faces[i] for i in valid_indices]
            
        elif rule == "all_except_bottom":
            z_coords = centroids[:, 2]
            valid_indices = np.where(z_coords >= (min_z + tol))[0]
            selected = [boundary_faces[i] for i in valid_indices]
            
        elif rule == "all":
            selected = list(boundary_faces)
            
        elif rule == "z_down_except_bottom":
            tol_excl = diag * 0.001
            z_coords = centroids[:, 2]
            candidates = np.where(z_coords >= (min_z + tol_excl))[0]
            
            for idx in candidates:
                face_nodes_idx = boundary_faces[idx]
                f_coords = nodes[list(face_nodes_idx)]
                normal = self._calculate_normal(f_coords)
                if normal[2] < -1e-3:  # Pointing down
                    selected.append(boundary_faces[idx])
            print(f"[DEBUG] z_down_except_bottom: Selected {len(selected)} faces.")
            
        elif rule == "z_up":
            for idx in range(len(boundary_faces)):
                face_nodes_idx = boundary_faces[idx]
                f_coords = nodes[list(face_nodes_idx)]
                normal = self._calculate_normal(f_coords)
                if normal[2] > 1e-3:  # Pointing up
                    selected.append(boundary_faces[idx])
            print(f"[DEBUG] z_up: Selected {len(selected)} faces.")
        
        return selected
    
    def _calculate_normal(self, coords):
        """Calculate face normal from 4 corner coordinates."""
        v1 = coords[1] - coords[0]
        v2 = coords[3] - coords[0]
        n = np.cross(v1, v2)
        norm = np.linalg.norm(n)
        return n / norm if norm > 0 else n


# Strategy registry
_STRATEGIES = {
    "A": RelativeBoundsStrategy(),
    "B": ProximityStrategy(),
    "GeometricRule": GeometricRuleStrategy(),
}

class SetReconstructor:
    def __init__(self, tree, part_name):
        """
        Args:
            tree (lxml.etree.ElementTree): The parsed FEBio XML tree.
            part_name (str): The name of the <Nodes> section being replaced.
        """
        self.tree = tree
        self.part_name = part_name
        self.root = tree.getroot()
        self.mesh_section = self.root.find("Mesh")
        
        if self.mesh_section is None:
            raise ValueError("No <Mesh> section found in XML.")

        # 1. Build a map of ALL original nodes: id -> (x, y, z)
        #    We need this to reconstruct the geometry of sets and partners.
        self.global_node_map = self._build_global_node_map()
        
        # 2. Identify the nodes belonging to the target part
        self.part_node_ids = self._identify_part_nodes()
        
        # Calculate bounding box of the ORIGINAL part
        part_coords = self._get_coords_by_ids(self.part_node_ids)
        self.part_bbox = geometry_utils.calculate_bounding_box(part_coords)
        
        # 3. Analyze sets to determine reconstruction strategy
        self.set_definitions = self._analyze_sets()

    def _build_global_node_map(self):
        node_map = {}
        for node in self.mesh_section.xpath("//Nodes/node"):
            try:
                nid = int(node.get("id"))
                coords = [float(x) for x in node.text.split(',')]
                node_map[nid] = np.array(coords)
            except (ValueError, AttributeError):
                continue
        return node_map

    def _identify_part_nodes(self):
        # Find the <Nodes name="part_name"> block
        target_nodes = None
        for nodes_node in self.mesh_section.findall("Nodes"):
            if nodes_node.get("name") == self.part_name:
                target_nodes = nodes_node
                break
        
        if target_nodes is None:
            raise ValueError(f"Could not find <Nodes name='{self.part_name}'>")
            
        ids = []
        for node in target_nodes.findall("node"):
            ids.append(int(node.get("id")))
        return set(ids)

    def _get_coords_by_ids(self, node_ids):
        coords = []
        for nid in node_ids:
            if nid in self.global_node_map:
                coords.append(self.global_node_map[nid])
        return np.array(coords)

    def _is_surface_on_this_part(self, surface_name):
        """Checks if all nodes of the given surface belong to the current part."""
        for s in self.mesh_section.findall("Surface"):
            if s.get("name") == surface_name:
                for elem in s:
                    if elem.text:
                        try:
                            nids = [int(x) for x in elem.text.replace(',', ' ').split()]
                            if not all(nid in self.part_node_ids for nid in nids):
                                return False
                        except: pass
                return True
        return False

    def _analyze_sets(self):
        """
        Identifies all NodeSets and Surfaces belonging to the replaced part.
        Determines if they follow Strategy A (Relative) or Strategy B (Proximity).
        """
        definitions = []
        
        # Helper map: surface_name -> partner_surface_name (for Strategy B)
        contact_partners = self._map_contact_partners()
        
        # --- Analyze NodeSets ---
        for nodeset in self.mesh_section.findall("NodeSet"):
            name = nodeset.get("name")
            ids = []
            for n in nodeset.findall("node"):
                try:
                    ids.append(int(n.get("id")))
                except: pass
            
            # Check if this set belongs to the part (all nodes in part_node_ids)
            if not ids or not all(nid in self.part_node_ids for nid in ids):
                continue
            
            # Strategy A for NodeSets
            coords = self._get_coords_by_ids(ids)
            rel_bounds = self._calculate_relative_bounds_for_check(coords)
            
            definitions.append({
                "type": "NodeSet",
                "name": name,
                "strategy": "A",
                "relative_bounds": rel_bounds
            })

        # --- Analyze Surfaces ---
        # Note: Surfaces define elements/faces, but we need to link them to our part's nodes.
        # FEBio Surface elements often look like <quad4 id="..">n1,n2,n3,n4</quad4>
        for surface in self.mesh_section.findall("Surface"):
            name = surface.get("name")
            surface_node_ids = set()
            faces_indices = [] # List of tuples of global Node IDs
            
            for elem in surface:
                if elem.text:
                    try:
                        nids = [int(x) for x in elem.text.replace(',', ' ').split()]
                        surface_node_ids.update(nids)
                        faces_indices.append(tuple(nids))
                    except: pass
            
            if not surface_node_ids:
                continue

            # Check if surface belongs to target part
            if not surface_node_ids.issubset(self.part_node_ids):
                continue

            # Check Strategy
            strategy = "A"
            partner_name = contact_partners.get(name)
            partner_geometry = None
            
            if partner_name:
                # Resolve partner geometry
                # We need to find the partner surface definition to get its geometry
                p_nodes, p_faces = self._get_surface_geometry(partner_name)
                
                # CHECK: Is partner surface also on THIS part? (Self-Contact)
                # If so, Proximity (B) is dangerous because it picks up adjacent faces.
                # Force Strategy A (Relative Bounds) for self-contact.
                is_self_contact = False
                if self._is_surface_on_this_part(partner_name):
                    is_self_contact = True
                    print(f"  [Refining] Set '{name}' has partner '{partner_name}' on SAME part -> Forcing Strategy A")
                    strategy = "A"
                elif p_nodes is not None and len(p_nodes) > 0:
                     # Calculate centroids for partner faces
                     p_centroids = geometry_utils.calculate_face_centroids(p_nodes, p_faces)
                     partner_geometry = p_centroids
                     strategy = "B"
            
            def_dict = {
                "type": "Surface",
                "name": name,
                "strategy": strategy,
                "faces_original": faces_indices
            }
            
            if strategy == "A":
                # For surfaces, we track centroids of faces
                # But to keep it robust against mesh changes, we track the *bounding box* of the surface
                # and maybe normal direction. 
                # Simplest Strategy A: Relative Bounds of the surface centroids.
                nodes_array = self._get_coords_by_ids(surface_node_ids)
                def_dict["relative_bounds"] = self._calculate_relative_bounds_for_check(nodes_array)
            else:
                def_dict["partner_centroids"] = partner_geometry
                
            definitions.append(def_dict)
            
        return definitions

    def _map_contact_partners(self):
        # Maps primary/secondary -> partner name
        partners = {}
        
        # FEBio 4.0 SurfacePair
        for sp in self.mesh_section.findall("SurfacePair"):
            p = sp.find("primary")
            s = sp.find("secondary")
            if p is not None and s is not None:
                p_name = p.text.strip()
                s_name = s.text.strip()
                partners[p_name] = s_name
                partners[s_name] = p_name
                
        # Older Contact syntax or other pair types might exist in root/Contact
        # But we focus on Mesh section definitions for now.
        return partners

    def _get_surface_geometry(self, surface_name):
        # Finds a surface by name and valid global node IDs + face connectivity (0-based for local use later)
        # Currently returns (global_coords_array, face_list_of_indices_into_array)
        
        target_surface = None
        for s in self.mesh_section.findall("Surface"):
            if s.get("name") == surface_name:
                target_surface = s
                break
        
        if not target_surface:
            return None, None
            
        # Collect all unique nodes and faces
        unique_nids = set()
        faces = [] # list of lists of global IDs
        
        for elem in target_surface:
            if elem.text:
                nids = [int(x) for x in elem.text.replace(',', ' ').split()]
                unique_nids.update(nids)
                faces.append(nids)
                
        sorted_nids = sorted(list(unique_nids))
        nid_to_idx = {nid: i for i, nid in enumerate(sorted_nids)}
        
        coords = self._get_coords_by_ids(sorted_nids)
        
        # Convert face global IDs to local indices into 'coords'
        local_faces = []
        for face_nids in faces:
            local_faces.append([nid_to_idx[nid] for nid in face_nids])
            
        return coords, local_faces

    def _calculate_relative_bounds_for_check(self, coords):
        # Returns specific relative bounds for a set of coordinates within part_bbox
        # Returns tuple of tuples ((min_x, min_y...), (max_x...))
        if len(coords) == 0:
            return ((0,0,0), (0,0,0))
            
        # Get absolute bbox of this set
        set_min, set_max = geometry_utils.calculate_bounding_box(coords)
        
        # Convert to relative
        rel_min = geometry_utils.get_relative_coordinates(set_min, self.part_bbox)
        rel_max = geometry_utils.get_relative_coordinates(set_max, self.part_bbox)
        
        return (tuple(rel_min), tuple(rel_max))

    def reconstruct(self, new_nodes, new_elements_connectivity):
        """
        Generates new set definitions based on the new mesh.
        Uses strategy pattern for cleaner implementation.
        
        Args:
            new_nodes: numpy array (N, 3)
            new_elements_connectivity: list of lists (Hex8 indices)
            
        Returns:
            dict: {
                "NodeSet": {name: [new_node_indices...]},
                "Surface": {name: [(n1, n2, n3, n4)...]} 
            }
        """
        results = {"NodeSet": {}, "Surface": {}}
        
        # Pre-calculations for new mesh
        new_bbox = geometry_utils.calculate_bounding_box(new_nodes)
        new_boundary_faces = geometry_utils.extract_boundary_faces(new_elements_connectivity)
        new_face_centroids = geometry_utils.calculate_face_centroids(new_nodes, new_boundary_faces)
        
        print(f"[DEBUG] reconstruct: new_bbox={new_bbox}")
        print(f"[DEBUG] reconstruct: found {len(new_boundary_faces)} boundary faces")
        print(f"[DEBUG] reconstruct: calculated centroids shape={new_face_centroids.shape}")
        
        # Process each set definition
        for d in self.set_definitions:
            name = d["name"]
            strategy_key = d["strategy"]
            
            if d["type"] == "NodeSet":
                if strategy_key == "A":
                    rel_bounds = d["relative_bounds"]
                    indices = geometry_utils.filter_nodes_by_relative_bounds(
                        new_nodes, rel_bounds, new_bbox
                    )
                    results["NodeSet"][name] = indices.tolist()
                    
            elif d["type"] == "Surface":
                # Use strategy pattern for surface selection
                strategy = _STRATEGIES.get(strategy_key)
                if strategy:
                    selected_faces = strategy.select_faces(
                        d, new_boundary_faces, new_face_centroids, new_nodes, new_bbox
                    )
                    results["Surface"][name] = selected_faces
                else:
                    print(f"[WARN] Unknown strategy '{strategy_key}' for surface '{name}'")
        
        return results
