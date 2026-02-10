import os
import numpy as np
import pyvista as pv

from src.libs.waffleiron import xplt


class WaffleironLoader:
    """Load .xplt data and cache per-step arrays for fast UI updates."""

    _VTK_TYPE_FROM_NAME = {
        "Hex8": 12,    # VTK_HEXAHEDRON
        "Tet4": 10,    # VTK_TETRA
        "Penta6": 13,  # VTK_WEDGE
        "Quad4": 9,    # VTK_QUAD
        "Tri3": 5,     # VTK_TRIANGLE
        "Hex20": 25,   # VTK_QUADRATIC_HEXAHEDRON
        "Tet10": 24,   # VTK_QUADRATIC_TETRA
    }

    _VTK_TYPE_FROM_N_NODES = {
        8: 12,
        4: 10,
        6: 13,
        20: 25,
    }

    def __init__(self, filepath):
        self.filepath = filepath
        self.xplt_data = None
        self.raw_mesh = None
        self.element_map = None  # element_id -> waffleiron element index
        self.rigid_body_offset = 0  # Number of rigid body elements at start
        self.w_mesh = None
        self._n_points = 0
        self._n_cells = 0
        self._step_cache = {}  # step_idx -> {"point": {name: np.ndarray}, "cell": {name: np.ndarray}}
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
        self._n_points = len(self.w_mesh.nodes)
        self._n_cells = len(self.w_mesh.elements)

    def get_mesh(self) -> pv.UnstructuredGrid:
        """
        Convert Waffleiron mesh to PyVista UnstructuredGrid.
        """
        points = np.asarray(self.w_mesh.nodes, dtype=float)

        cell_types = []
        cells = []
        for el in self.w_mesh.elements:
            node_ids = el.ids
            n_nodes = len(node_ids)

            el_type_name = el.__class__.__name__
            vtk_type = self._VTK_TYPE_FROM_NAME.get(el_type_name)
            if vtk_type is None:
                vtk_type = self._VTK_TYPE_FROM_N_NODES.get(n_nodes)
                if vtk_type is None:
                    continue

            cell_types.append(vtk_type)
            cells.append(n_nodes)
            cells.extend(node_ids)

        cells = np.asarray(cells)
        cell_types = np.asarray(cell_types, dtype=np.uint8)
        return pv.UnstructuredGrid(cells, cell_types, points)

    def get_time_steps(self):
        """Return list of time values for each step."""
        return self.xplt_data.step_times

    def _to_numpy_array(self, values):
        """Convert step values to ndarray while handling nested/object layouts."""
        try:
            arr = np.asarray(values, dtype=float)
        except Exception:
            arr = np.asarray(values)
            if arr.dtype == object:
                try:
                    arr = np.asarray(values, dtype=float)
                except Exception:
                    arr = np.asarray(values)
        return arr

    def _normalize_domain_array(self, arr):
        """
        Convert domain array length to n_cells.

        - n == n_cells: direct
        - n < n_cells: right-align with NaN padding (rigid/excluded domain)
        - n > n_cells and divisible: treat as per-integration-point and average
        """
        if arr.ndim == 0:
            return None

        data_len = arr.shape[0]
        n_cells = self._n_cells

        if data_len == n_cells:
            return np.asarray(arr)

        if data_len < n_cells:
            offset = n_cells - data_len
            if arr.ndim == 1:
                out_arr = np.full(n_cells, np.nan, dtype=float)
                out_arr[offset:] = arr
            else:
                out_shape = (n_cells,) + tuple(arr.shape[1:])
                out_arr = np.full(out_shape, np.nan, dtype=float)
                out_arr[offset:] = arr
            return out_arr

        if data_len > n_cells and data_len % n_cells == 0:
            group = data_len // n_cells
            if arr.ndim == 1:
                return arr.reshape(n_cells, group).mean(axis=1)
            reshaped = arr.reshape((n_cells, group) + tuple(arr.shape[1:]))
            return reshaped.mean(axis=1)

        return None

    def _build_step_cache(self, step_idx: int):
        """Parse and cache one step's point/cell arrays."""
        step_data = self.xplt_data.step_data(step_idx)
        point_data = {}
        cell_data = {}

        for (var_name, region_type), values in step_data.items():
            if var_name == "time" or values is None:
                continue
            try:
                if len(values) == 0:
                    continue
            except TypeError:
                pass

            arr = self._to_numpy_array(values)
            if arr.size == 0:
                continue

            if region_type == "node":
                if arr.ndim > 0 and arr.shape[0] == self._n_points:
                    point_data[var_name] = np.asarray(arr)
                continue

            if region_type == "domain":
                norm_arr = self._normalize_domain_array(arr)
                if norm_arr is not None:
                    cell_data[var_name] = norm_arr

        cached = {"point": point_data, "cell": cell_data}
        self._step_cache[step_idx] = cached
        return cached

    def preload_steps(self, progress_callback=None):
        """Build cache for all steps. Intended to run in a background thread."""
        total = len(self.xplt_data.step_blocks)
        if total == 0:
            return
        for idx in range(total):
            if idx not in self._step_cache:
                self._build_step_cache(idx)
            if progress_callback and (idx == 0 or (idx + 1) % 5 == 0 or idx == total - 1):
                progress_callback(f"Caching step data... ({idx + 1}/{total})")

    def load_step_result(self, grid: pv.UnstructuredGrid, step_idx: int):
        """
        Load results for specific step into the grid.
        Modifies grid in-place.
        """
        if step_idx < 0 or step_idx >= len(self.xplt_data.step_blocks):
            return

        cached = self._step_cache.get(step_idx)
        if cached is None:
            cached = self._build_step_cache(step_idx)

        for name, arr in cached["point"].items():
            grid.point_data[name] = arr
        for name, arr in cached["cell"].items():
            grid.cell_data[name] = arr
