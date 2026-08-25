"""
Compatibility wrapper for mesh_swap geometry helpers.

Historically, mesh_swap imported utilities from ``src.mesh_swap.geometry_utils``.
The shared implementations now live in ``src.utils.geometry``. Re-export them
here so the existing callers keep working.
"""

from ..utils.geometry import *  # noqa: F401,F403
