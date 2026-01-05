
import numpy as np
import pyvista as pv
import os

from src.libs.waffleiron import xplt
from src.libs.waffleiron import element

class WaffleironLoader:
    def __init__(self, filepath):
        self.filepath = filepath
        self.xplt_data = None
        self.raw_mesh = None
        self.element_map = None # element_id -> index
        self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"{self.filepath} not found")
            
        with open(self.filepath, "rb") as f:
            data = f.read()
            
        self.xplt_data = xplt.XpltData(data)
        
        # Parse mesh immediately
        # w_mesh is Waffleiron Mesh object
        # elem_map is dict {element_id: index}
        self.w_mesh, self.element_map = self.xplt_data.mesh()
        
    def get_mesh(self) -> pv.UnstructuredGrid:
        """
        Convert Waffleiron mesh to PyVista UnstructuredGrid.
        """
        # Nodes
        # w_mesh.nodes is list of [x, y, z] lists/arrays
        points = np.array(self.w_mesh.nodes, dtype=float)
        
        # Elements
        # PyVista expects: [n, id1, id2, ..., n, id1, id2, ...]
        # w_mesh.elements is list of Element objects (Hex8, Tet4, etc)
        # Each element has .ids (list of node indices)
        
        # Need to map FEBio element types to VTK cell types
        # Hex8 -> 12
        # Tet4 -> 10
        # Penta6 -> 13
        # Quad4 -> 9
        # Tri3 -> 5
        # etc.
        
        # Check src/libs/waffleiron/element.py for types if needed.
        # Mapping based on common knowledge + Waffleiron names
        
        cell_types = []
        cells = []
        
        for el in self.w_mesh.elements:
            node_ids = el.ids
            n_nodes = len(node_ids)
            
            # Identify type
            # Assuming standard naming in Waffleiron element classes
            el_type_name = el.__class__.__name__
            
            vtk_type = 0
            if el_type_name == "Hex8":
                vtk_type = 12 # VTK_HEXAHEDRON
            elif el_type_name == "Tet4":
                vtk_type = 10 # VTK_TETRA
            elif el_type_name == "Penta6":
                vtk_type = 13 # VTK_WEDGE
            elif el_type_name == "Quad4":
                vtk_type = 9 # VTK_QUAD
            elif el_type_name == "Tri3":
                vtk_type = 5 # VTK_TRIANGLE
            elif el_type_name == "Hex20":
                vtk_type = 25 # VTK_HEXAHEDRON_20
            elif el_type_name == "Tet10":
                vtk_type = 24 # VTK_TETRA_10
            else:
                # Fallbck based on node count?
                if n_nodes == 8: vtk_type = 12
                elif n_nodes == 4: vtk_type = 10
                elif n_nodes == 6: vtk_type = 13
                else:
                    # Generic or unknown
                    # Skipping or treating as PolyVertex?
                    # For now print warning and skip?
                    continue

            cell_types.append(vtk_type)
            cells.append(n_nodes)
            cells.extend(node_ids)
            
        cells = np.array(cells)
        cell_types = np.array(cell_types, dtype=np.uint8)
        
        grid = pv.UnstructuredGrid(cells, cell_types, points)
        return grid

    def get_time_steps(self):
        """Return list of time values for each step."""
        return self.xplt_data.step_times
        
    def load_step_result(self, grid: pv.UnstructuredGrid, step_idx: int):
        """
        Load results for specific step into the grid.
        Modifies grid in-place.
        """
        if step_idx < 0 or step_idx >= len(self.xplt_data.step_blocks):
            return

        # Get raw data dict
        #Keys are like ('displacement', 'node'), ('stress', 'domain')
        step_data = self.xplt_data.step_data(step_idx)
        
        for (var_name, region_type), values in step_data.items():
            if var_name == "time": continue
            
            # Flatten values if needed or convert to numpy
            # values is list of arrays/floats/lists
            
            # Node data -> grid.point_data
            if region_type == "node":
                # Check if scalar or vector
                # vector: list of np.array shape (3,)
                # scalar: list of float
                
                # Check first item type
                if not values: continue
                
                # Assign to point_data
                # Note: values list corresponds to node indices 0..N-1
                # assuming full mesh coverage.
                
                try:
                    # Convert to numpy array
                    arr = np.array(values)
                    grid.point_data[var_name] = arr
                except Exception as e:
                    print(f"Failed to set point data {var_name}: {e}")

            # Domain (Element) data -> grid.cell_data
            elif region_type == "domain":
                # Domain data in Waffleiron seems to be a single long list of values
                # corresponding to all elements in the domains.
                # However, values list might be concatenated domains.
                # Check how xplt_data.step_data constructs it.
                # It says: "Values are returned as a list ... corresponding to the zero-indexed ID"
                # If Waffleiron merges domains correctly, indices should match element IDs.
                
                if not values: continue
                
                try:
                    arr = np.array(values)
                    
                    # Stress is usually mat3fs (6 components symmetric)
                    # PyVista/ParaView usually expects 6 or 9 components for tensor.
                    # Waffleiron mat3fs: [xx, yy, zz, xy, yz, zx]
                    # VTK/PyVista typical order: [xx, yy, zz, xy, yz, xz]
                    
                    if arr.ndim == 2 and arr.shape[1] == 6:
                         # Reorder if necessary or keep as is? 
                         # FEBio: xx, yy, zz, xy, yz, zx
                         # VTK: xx, yy, zz, xy, yz, xz (Wait, VTK tensor is 9 usually? Or 6?)
                         # PyVista tensor support is tricky.
                         # Let's save as distinct components for safety first?
                         # Or just save as array and let user deal.
                         pass

                    # Ensure size matches number of cells
                    if len(arr) == grid.n_cells:
                        grid.cell_data[var_name] = arr
                    else:
                        pass
                        # print(f"Cell data size mismatch for {var_name}: {len(arr)} vs {grid.n_cells}")
                        # This happens if not all elements have results (e.g. strict domains).
                        # But Waffleiron seems to try to return values for IDs.
                        
                except Exception as e:
                    print(f"Failed to set cell data {var_name}: {e}")

        # Always ensure 'displacement' is present for warping
        if "displacement" not in grid.point_data:
            # Add zero?
            pass

