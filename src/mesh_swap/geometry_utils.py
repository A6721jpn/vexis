"""
Geometry utilities for mesh_swap module.
Re-exports from src.utils.geometry for backward compatibility.
"""

# Re-export all from the new common geometry module
from src.utils.geometry import (
    calculate_bounding_box,
    get_relative_coordinates,
    get_absolute_coordinates,
    calculate_face_centroids,
    build_kdtree,
    query_kdtree_distance,
    filter_nodes_by_relative_bounds,
    extract_boundary_faces,
    tfi_blend,
)

# Also export for direct numpy usage in this module
import numpy as np
