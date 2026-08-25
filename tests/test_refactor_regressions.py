from pathlib import Path


def test_mesh_swap_geometry_utils_reexports_shared_helpers():
    from src.mesh_swap import geometry_utils

    required_names = [
        "calculate_bounding_box",
        "get_relative_coordinates",
        "calculate_face_centroids",
        "build_kdtree",
        "query_kdtree_distance",
        "filter_nodes_by_relative_bounds",
        "extract_boundary_faces",
    ]

    missing = [name for name in required_names if not hasattr(geometry_utils, name)]

    assert missing == []


def test_set_reconstructor_initializes_for_template_rubber():
    from src.mesh_swap.mesh_replacer import load_reference
    from src.mesh_swap.set_reconstructor import SetReconstructor

    template = Path(__file__).resolve().parents[1] / "template2.feb"
    tree = load_reference(str(template))

    reconstructor = SetReconstructor(tree, "RUBBER_OBJ")
    preserved_sets = {definition["name"] for definition in reconstructor.set_definitions}

    assert "RUBBER_SELF_CONTACTPrimary" in preserved_sets
    assert "RUBBER_SELF_CONTACTSecondary" in preserved_sets
