
import numpy as np
from scipy.spatial import KDTree

def calculate_bounding_box(nodes):
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
        
    min_coords = np.min(nodes, axis=0)
    max_coords = np.max(nodes, axis=0)
    return min_coords, max_coords

def get_relative_coordinates(node, bbox):
    """
    Converts absolute coordinates to relative coordinates (0-1) within a bounding box.
    
    Args:
        node: A numpy array representing a point (3,).
        bbox: A tuple (min_coords, max_coords).
        
    Returns:
        numpy array: Relative coordinates (3,). Returns nan or inf if bbox has zero width.
    """
    min_c, max_c = bbox
    dimensions = max_c - min_c
    
    # Avoid division by zero
    dimensions = np.where(dimensions == 0, 1.0, dimensions)
    
    relative_coords = (node - min_c) / dimensions
    return relative_coords

def get_absolute_coordinates(relative_coords, bbox):
    """
    Converts relative coordinates back to absolute coordinates within a bounding box.
    
    Args:
        relative_coords: A numpy array representing relative position (3,).
        bbox: A tuple (min_coords, max_coords).
        
    Returns:
        numpy array: Absolute coordinates (3,).
    """
    min_c, max_c = bbox
    dimensions = max_c - min_c
    
    abs_coords = min_c + (relative_coords * dimensions)
    return abs_coords

def calculate_face_centroids(nodes, faces):
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
    centroids = []
    
    for face_indices in faces:
        face_nodes = nodes[list(face_indices)]
        centroid = np.mean(face_nodes, axis=0)
        centroids.append(centroid)
        
    return np.array(centroids)

def build_kdtree(points):
    """
    Builds a KDTree for fast spatial queries.
    
    Args:
        points: A numpy array of 3D points (N, 3).
        
    Returns:
        scipy.spatial.KDTree
    """
    return KDTree(points)

def query_kdtree_distance(kdtree, points, distance_upper_bound=np.inf):
    """
    Finds the distance to the nearest neighbor in the KDTree for each query point.
    
    Args:
        kdtree: The KDTree built on the reference points (e.g., target surface).
        points: The points to query (e.g., candidates in the new mesh).
        distance_upper_bound: Maximum distance to consider. Points further away will report inf distance.
        
    Returns:
        distances: Array of distances to nearest neighbor.
        indices: Array of indices of the nearest neighbor in the tree.
    """
    distances, indices = kdtree.query(points, distance_upper_bound=distance_upper_bound)
    return distances, indices

def filter_nodes_by_relative_bounds(nodes, relative_bounds, global_bbox):
    """
    Filters nodes that fall within specific relative bounds of the global bounding box.
    
    Args:
        nodes: Numpy array of node coordinates (N, 3).
        relative_bounds: Tuple of ((x_min, y_min, z_min), (x_max, y_max, z_max)) in 0-1 range.
        global_bbox: The bounding box of the 'nodes' set or the global part.
        
    Returns:
        indices: Indices of nodes that satisfy the bounds.
    """
    min_c, max_c = global_bbox
    dims = max_c - min_c
    
    # Calculate absolute bounds for the filter
    # relative_bounds[0] is min ratios, relative_bounds[1] is max ratios
    
    abs_min = min_c + np.array(relative_bounds[0]) * dims
    abs_max = min_c + np.array(relative_bounds[1]) * dims
    
    # Add a small tolerance to handle floating point issues at boundaries
    tolerance = 1e-6 * np.linalg.norm(dims)
    
    in_bounds_mask = np.all((nodes >= abs_min - tolerance) & (nodes <= abs_max + tolerance), axis=1)
    
    return np.where(in_bounds_mask)[0]

def extract_boundary_faces(elements):
    """
    Extracts the boundary faces from a list of volume elements (Hex8).
    Assumes standard Hex8 numbering.
    
    Args:
        elements: List or numpy array of Hex8 connectivity (N, 8).
        
    Returns:
        list of tuples: Each tuple contains the 4 node indices of a boundary face.
                        The order of nodes preserves the outward normal convention.
    """
    elements = np.asarray(elements)
    
    # Hex8 face definitions (indices into 0-7)
    # FEBio/standard convention for outward normals
    # Hex20 note: faces are Quad8.
    # Winding: corners then mid-edges.
    # Hex20 numbering:
    # 0-7: corners
    # 8-19: edges (0-1, 1-2, 2-3, 3-0, 4-5, 5-6, 6-7, 7-4, 0-4, 1-5, 2-6, 3-7)
    
    # Check dimensions
    num_nodes = elements.shape[1]
    
    if num_nodes == 8:
        face_defs = [
            [0, 3, 2, 1], # Bottom
            [4, 5, 6, 7], # Top
            [0, 1, 5, 4], # Front
            [1, 2, 6, 5], # Right
            [2, 3, 7, 6], # Back
            [3, 0, 4, 7]  # Left
        ]
    elif num_nodes == 20:
        # Hex20 faces (Quad8)
        # Using VTK numbering convention for indices
        # Bottom: 0, 3, 2, 1, 11, 10, 9, 8 
        #   0-3 (11), 3-2 (10), 2-1 (9), 1-0 (8) -- Wait VTK edge 8 is 0-1.
        #   Edges: 8(0-1), 9(1-2), 10(2-3), 11(3-0)
        #   So: 0, 3, 2, 1 -> Edges: 3-0? (11), 2-3? (10), 1-2? (9), 0-1? (8)
        #   Order: corner, corner, corner, corner, mid, mid, mid, mid 
        #   CCW: 0 -> 3 -> 2 -> 1
        #   Mid 0-3 (11), Mid 3-2 (10), Mid 2-1 (9), Mid 1-0 (8)
        #   So [0, 3, 2, 1, 11, 10, 9, 8]
        
        # Top: 4, 5, 6, 7 (CCW from top)
        #   Edges: 4-5 (12), 5-6 (13), 6-7 (14), 7-4 (15)
        #   [4, 5, 6, 7, 12, 13, 14, 15]
        
        # Front: 0, 1, 5, 4
        #   Edges: 0-1 (8), 1-5 (17), 5-4 (12?), 4-0 (16)
        #   Wait 5-4 edge is 12? VTK edge 12 is 4-5. So 12 is correct (undirected).
        #   [0, 1, 5, 4, 8, 17, 12, 16]
        
        # Right: 1, 2, 6, 5
        #   Edges: 1-2 (9), 2-6 (18), 6-5 (13), 5-1 (17)
        #   [1, 2, 6, 5, 9, 18, 13, 17]
        
        # Back: 2, 3, 7, 6
        #   Edges: 2-3 (10), 3-7 (19), 7-6 (14), 6-2 (18)
        #   [2, 3, 7, 6, 10, 19, 14, 18]
        
        # Left: 3, 0, 4, 7
        #   Edges: 3-0 (11), 0-4 (16), 4-7 (15), 7-3 (19)
        #   [3, 0, 4, 7, 11, 16, 15, 19]
             
        face_defs = [
            [0, 3, 2, 1, 11, 10, 9, 8],
            [4, 5, 6, 7, 12, 13, 14, 15],
            [0, 1, 5, 4, 8, 17, 12, 16],
            [1, 2, 6, 5, 9, 18, 13, 17],
            [2, 3, 7, 6, 10, 19, 14, 18],
            [3, 0, 4, 7, 11, 16, 15, 19]
        ]
    else:
        # Default or fail
        return []

    # Flatten all faces into a large array (N*6, M)
    # Dictionary: tuple(sorted_indices) -> list of (original_indices)
    face_counts = {}
    
    for elem in elements:
        for f_def in face_defs:
            face_nodes = tuple(elem[f_def])
            # Key must be sorted based on corners (first 4 nodes) to be robust?
            # Or sorted all nodes? Sorted all nodes is definitive unique ID for the face.
            key = tuple(sorted(face_nodes))
            
            if key in face_counts:
                face_counts[key].append(face_nodes)
            else:
                face_counts[key] = [face_nodes]
    
    boundary_faces = []
    
    for key, occurrences in face_counts.items():
        if len(occurrences) == 1:
            boundary_faces.append(occurrences[0])
            
    return boundary_faces
