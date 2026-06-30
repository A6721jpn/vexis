from pathlib import Path

import pytest


def test_mesh_swap_geometry_utils_reexports_shared_helpers():
    from src.mesh_swap import geometry_utils

    required_names = [
        "calculate_bounding_box",
        "get_relative_coordinates",
        "get_absolute_coordinates",
        "calculate_face_centroids",
        "build_kdtree",
        "query_kdtree_distance",
        "filter_nodes_by_relative_bounds",
        "extract_boundary_faces",
        "tfi_blend",
    ]

    missing = [name for name in required_names if not hasattr(geometry_utils, name)]

    assert missing == []


@pytest.mark.filterwarnings("error::FutureWarning")
def test_set_reconstructor_initializes_template_rubber_contact_sets():
    from src.mesh_swap.mesh_replacer import load_reference
    from src.mesh_swap.set_reconstructor import SetReconstructor

    template = Path(__file__).resolve().parents[1] / "template2.feb"
    tree = load_reference(str(template))

    reconstructor = SetReconstructor(tree, "RUBBER_OBJ")
    preserved_sets = {definition["name"] for definition in reconstructor.set_definitions}

    assert len(reconstructor.set_definitions) == 7
    assert "TOP_CONTACTPrimary" in preserved_sets
    assert "RUBBER_BOTTOM_CONTACTPrimary" in preserved_sets
    assert "RUBBER_SELF_CONTACTPrimary" in preserved_sets
    assert "RUBBER_SELF_CONTACTSecondary" in preserved_sets
