import felupe as fe
import meshio
import numpy as np
import pytest


def test_inp_writer_does_not_pass_binary_kwarg(monkeypatch):
    from src.mesh_gen import utils

    calls = []

    class DummyMesh:
        def as_meshio(self):
            return meshio.Mesh(
                np.zeros((8, 3), dtype=float),
                [("hexahedron", np.array([[0, 1, 2, 3, 4, 5, 6, 7]], dtype=int))],
            )

    def fake_write(path, mesh, **kwargs):
        calls.append((path, mesh, kwargs))
        assert "binary" not in kwargs
        assert kwargs["file_format"] == "abaqus"

    monkeypatch.setattr(utils.meshio, "write", fake_write)

    utils.save_mesh_with_optional_quadratic(DummyMesh(), "temp/sample.inp", 1)

    assert calls == [("temp/sample.inp", calls[0][1], {"file_format": "abaqus"})]


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("inp", ["temp/sample.inp"]),
        ("vtk", []),
        ("msh", []),
    ],
)
def test_maybe_save_inp_sidecar_honors_output_format(
    monkeypatch, output_format, expected
):
    from src.mesh_gen import utils

    calls = []

    def fake_save(mesh, output_path, element_order):
        calls.append(output_path)
        assert mesh == "mesh"
        assert element_order == 2

    monkeypatch.setattr(utils, "save_mesh_with_optional_quadratic", fake_save)

    utils.maybe_save_inp_sidecar(
        "mesh",
        "temp/sample.vtk",
        element_order=2,
        output_format=output_format,
    )

    assert calls == expected


def test_quadratic_inp_export_writes_abaqus_hex20(tmp_path):
    from src.mesh_gen import utils

    points = np.array(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 0],
            [0, 1, 0],
            [0, 0, 1],
            [1, 0, 1],
            [1, 1, 1],
            [0, 1, 1],
        ],
        dtype=float,
    )
    cells = np.array([[0, 1, 2, 3, 4, 5, 6, 7]], dtype=int)
    mesh = fe.Mesh(points, cells, "hexahedron")
    out = tmp_path / "sample.inp"

    utils.save_mesh_with_optional_quadratic(mesh, str(out), 2)

    assert "*ELEMENT, TYPE=C3D20RH" in out.read_text(encoding="utf-8")
