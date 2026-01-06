"""
Common geometry utilities for VEXIS-CAE.
Provides bounding box, coordinate transformations, and mesh operations.
"""

import numpy as np
from scipy.spatial import KDTree
from typing import Tuple, List, Optional


def calculate_bounding_box(nodes: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calculates the 3D bounding box of a set of nodes.
    
    Args:
        nodes: A numpy array or list of coordinates (N, 3).
        
    Returns:
        tuple: (min_coords, max_coords) where each is a numpy array of shape (3,).
    """
    nodes = np.asarray(nodes)
    if nodes.size == 0:
        return np.zeros(3), np.zeros(3)
    return np.min(nodes, axis=0), np.max(nodes, axis=0)


def get_relative_coordinates(node: np.ndarray, bbox: Tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """
    Converts absolute coordinates to relative coordinates (0-1) within a bounding box.
    
    Args:
        node: A numpy array representing a point (3,).
        bbox: A tuple (min_coords, max_coords).
        
    Returns:
        numpy array: Relative coordinates (3,). Returns nan or inf if bbox has zero width.
    """
    min_c, max_c = bbox
    extent = max_c - min_c
    # Avoid division by zero
    with np.errstate(divide='ignore', invalid='ignore'):
        return (np.asarray(node) - min_c) / np.where(extent == 0, np.inf, extent)


def get_absolute_coordinates(relative_coords: np.ndarray, bbox: Tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """
    Converts relative coordinates back to absolute coordinates within a bounding box.
    
    Args:
        relative_coords: A numpy array representing relative position (3,).
        bbox: A tuple (min_coords, max_coords).
        
    Returns:
        numpy array: Absolute coordinates (3,).
    """
    min_c, max_c = bbox
    extent = max_c - min_c
    return min_c + np.asarray(relative_coords) * extent


def calculate_face_centroids(nodes: np.ndarray, faces: List) -> np.ndarray:
    """
    Calculates the centroids of faces.
    
    Args:
        nodes: A numpy array of node coordinates (element nodes).
        faces: A list or array of lists, where each inner list contains node INDICES for a face.
               Example: [[0, 1, 2, 3], [4, 5, 6, 7], ...]
               
    Returns:
        numpy array: Centroids of the faces (M, 3).
    """
    nodes = np.asarray(nodes)
    centroids = np.array([nodes[list(f)].mean(axis=0) for f in faces])
    return centroids if len(centroids) > 0 else np.zeros((0, 3))


def build_kdtree(points: np.ndarray) -> KDTree:
    """
    Builds a KDTree for fast spatial queries.
    
    Args:
        points: A numpy array of 3D points (N, 3).
        
    Returns:
        scipy.spatial.KDTree
    """
    return KDTree(np.asarray(points))


def query_kdtree_distance(kdtree: KDTree, points: np.ndarray, 
                          distance_upper_bound: float = np.inf) -> Tuple[np.ndarray, np.ndarray]:
    """
    Finds the distance to the nearest neighbor in the KDTree for each query point.
    
    Args:
        kdtree: The KDTree built on the reference points.
        points: Query points (N, 3).
        distance_upper_bound: Maximum search distance.
        
    Returns:
        distances: Array of distances to nearest neighbor.
        indices: Array of indices of the nearest neighbor in the tree.
    """
    return kdtree.query(np.asarray(points), distance_upper_bound=distance_upper_bound)


def filter_nodes_by_relative_bounds(nodes: np.ndarray, relative_bounds: Tuple, 
                                    global_bbox: Tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """
    Filters nodes that fall within specific relative bounds of the global bounding box.
    
    Args:
        nodes: Numpy array of node coordinates (N, 3).
        relative_bounds: Tuple ((min_x, min_y, min_z), (max_x, max_y, max_z)) in relative coords.
        global_bbox: The bounding box of the 'nodes' set or the global part.
        
    Returns:
        indices: Indices of nodes that satisfy the bounds.
    """
    nodes = np.asarray(nodes)
    rel_min, rel_max = relative_bounds
    rel_min, rel_max = np.asarray(rel_min), np.asarray(rel_max)
    
    # Add tolerance
    tol = 0.05
    rel_min_tol = np.maximum(rel_min - tol, 0.0)
    rel_max_tol = np.minimum(rel_max + tol, 1.0)
    
    # Convert each node to relative coordinates and check bounds
    valid_indices = []
    for i, node in enumerate(nodes):
        rel = get_relative_coordinates(node, global_bbox)
        if np.all(rel >= rel_min_tol) and np.all(rel <= rel_max_tol):
            valid_indices.append(i)
    
    return np.array(valid_indices, dtype=int)


def extract_boundary_faces(elements: List) -> List[Tuple]:
    """
    Extracts the boundary faces from a list of volume elements (Hex8 or Hex20).
    Supports both 8-node and 20-node hexahedral elements.
    
    Args:
        elements: List or numpy array of Hex8 (N, 8) or Hex20 (N, 20) connectivity.
        
    Returns:
        list of tuples: Each tuple contains the node indices of a boundary face.
                        For Hex8: 4-node faces (Quad4)
                        For Hex20: 8-node faces (Quad8)
    """
    if len(elements) == 0:
        return []
    
    # Detect element type from first element
    num_nodes = len(elements[0])
    
    if num_nodes == 8:
        # Hex8 face definitions (indices into element connectivity) - 4 nodes per face
        face_defs = [
            (0, 3, 2, 1),  # Bottom
            (4, 5, 6, 7),  # Top
            (0, 1, 5, 4),  # Front
            (2, 3, 7, 6),  # Back
            (0, 4, 7, 3),  # Left
            (1, 2, 6, 5),  # Right
        ]
    elif num_nodes == 20:
        # Hex20 face definitions - 8 nodes per face (corners + mid-edge nodes)
        # Hex20 numbering: 0-7 corners, 8-19 mid-edge nodes
        # Edge ordering: 8(0-1), 9(1-2), 10(2-3), 11(3-0), 12(4-5), 13(5-6), 14(6-7), 15(7-4), 16(0-4), 17(1-5), 18(2-6), 19(3-7)
        face_defs = [
            (0, 3, 2, 1, 11, 10, 9, 8),     # Bottom: corners 0,3,2,1 + edges 11,10,9,8
            (4, 5, 6, 7, 12, 13, 14, 15),   # Top: corners 4,5,6,7 + edges 12,13,14,15
            (0, 1, 5, 4, 8, 17, 12, 16),    # Front: corners 0,1,5,4 + edges 8,17,12,16
            (1, 2, 6, 5, 9, 18, 13, 17),    # Right: corners 1,2,6,5 + edges 9,18,13,17
            (2, 3, 7, 6, 10, 19, 14, 18),   # Back: corners 2,3,7,6 + edges 10,19,14,18
            (3, 0, 4, 7, 11, 16, 15, 19),   # Left: corners 3,0,4,7 + edges 11,16,15,19
        ]
    else:
        # Unsupported element type
        print(f"[WARN] extract_boundary_faces: Unsupported element type with {num_nodes} nodes")
        return []
    
    face_count = {}
    face_to_nodes = {}
    
    for elem in elements:
        elem = list(elem)
        for face_def in face_defs:
            face_nodes = tuple(elem[i] for i in face_def)
            # Create canonical key using only corner nodes (first 4) for uniqueness
            face_key = tuple(sorted(face_nodes[:4]))
            face_count[face_key] = face_count.get(face_key, 0) + 1
            face_to_nodes[face_key] = face_nodes
    
    # Boundary faces appear exactly once
    boundary_faces = [face_to_nodes[k] for k, v in face_count.items() if v == 1]
    return boundary_faces


def tfi_blend(s: float, t: float, 
              P00: np.ndarray, P10: np.ndarray, P01: np.ndarray, P11: np.ndarray,
              B: np.ndarray, T: np.ndarray, L: np.ndarray, R: np.ndarray) -> np.ndarray:
    """
    Transfinite Interpolation (Coons patch) blending.
    
    Computes the interior point given: 
      - corner points P00, P10, P01, P11
      - boundary points B(bottom), T(top), L(left), R(right) at (s,t)
    
    Args:
        s, t: Parametric coordinates in [0,1]
        P00, P10, P01, P11: Corner points
        B, T, L, R: Boundary points at (s,t)
        
    Returns:
        Blended interior point
    """
    P = (1 - t) * B + t * T + (1 - s) * L + s * R
    P -= (1 - s) * (1 - t) * P00 + s * (1 - t) * P10 + (1 - s) * t * P01 + s * t * P11
    return P
