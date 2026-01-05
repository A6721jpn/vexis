
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
        self.element_map = None  # element_id -> waffleiron element index
        self.rigid_body_offset = 0  # Number of rigid body elements at start
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
        points = np.array(self.w_mesh.nodes, dtype=float)
        
        # Elements
        cell_types = []
        cells = []
        
        for el in self.w_mesh.elements:
            node_ids = el.ids
            n_nodes = len(node_ids)
            
            # Identify VTK type from element class name
            el_type_name = el.__class__.__name__
            
            vtk_type = 0
            if el_type_name == "Hex8":
                vtk_type = 12  # VTK_HEXAHEDRON
            elif el_type_name == "Tet4":
                vtk_type = 10  # VTK_TETRA
            elif el_type_name == "Penta6":
                vtk_type = 13  # VTK_WEDGE
            elif el_type_name == "Quad4":
                vtk_type = 9   # VTK_QUAD
            elif el_type_name == "Tri3":
                vtk_type = 5   # VTK_TRIANGLE
            elif el_type_name == "Hex20":
                vtk_type = 25  # VTK_QUADRATIC_HEXAHEDRON
            elif el_type_name == "Tet10":
                vtk_type = 24  # VTK_QUADRATIC_TETRA
            else:
                # Fallback based on node count
                if n_nodes == 8: vtk_type = 12
                elif n_nodes == 4: vtk_type = 10
                elif n_nodes == 6: vtk_type = 13
                elif n_nodes == 20: vtk_type = 25
                else:
                    continue  # Skip unknown element types

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
        # Keys are like ('displacement', 'node'), ('stress', 'domain')
        step_data = self.xplt_data.step_data(step_idx)
        
        for (var_name, region_type), values in step_data.items():
            if var_name == "time": continue
            
            # Node data -> grid.point_data
            if region_type == "node":
                if not values: continue
                
                try:
                    arr = np.array(values)
                    grid.point_data[var_name] = arr
                except Exception as e:
                    print(f"Failed to set point data {var_name}: {e}")

            # Domain (Element) data -> grid.cell_data
            elif region_type == "domain":
                if not values: continue
                
                try:
                    # Convert to numpy
                    try:
                        arr = np.array(values, dtype=float)
                    except Exception:
                        arr = np.array(values)
                        if arr.dtype == object:
                            arr = np.vstack(values).astype(float)
                    
                    data_len = len(arr)
                    n_cells = grid.n_cells
                    
                    # Calculate offset: rigid body elements at the start don't have domain data
                    # Domain data length < grid cells means some elements are rigid/excluded
                    offset = n_cells - data_len
                    
                    # Create output array with NaN for cells without data
                    if arr.ndim == 1:
                        out_arr = np.full(n_cells, np.nan, dtype=float)
                        out_arr[offset:] = arr
                    else:
                        out_arr = np.full((n_cells,) + arr.shape[1:], np.nan, dtype=float)
                        out_arr[offset:] = arr
                    
                    grid.cell_data[var_name] = out_arr
                        
                except Exception as e:
                    print(f"Failed to set cell data {var_name}: {e}")

        # Always ensure 'displacement' is present for warping
        if "displacement" not in grid.point_data:
            pass
