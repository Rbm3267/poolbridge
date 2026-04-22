"""Contour line generation from scattered elevation points (GR shots).

Uses scipy.interpolate.griddata for surface interpolation and a marching-squares
algorithm for iso-elevation line extraction.  Returns raw line segments that the
DXF writer places on V-TOPO-MAJR / V-TOPO-MINR layers.
"""

import logging
import math
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

Segment = Tuple[Tuple[float, float], Tuple[float, float]]

# ---------------------------------------------------------------------------
# Marching-squares lookup table
#
# Corner indices:  c2 --- c3        Case = c0*1 + c1*2 + c2*4 + c3*8
#                  |       |        (corner above threshold → bit set)
#                  c0 --- c1
#
# Edge indices: 0=bottom(c0-c1)  1=right(c1-c3)  2=top(c2-c3)  3=left(c0-c2)
# ---------------------------------------------------------------------------
_CASE_SEGS: List[List[Tuple[int, int]]] = [
    [],                 # 0  — all below
    [(0, 3)],           # 1  — c0 above
    [(0, 1)],           # 2  — c1 above
    [(1, 3)],           # 3  — c0,c1 above
    [(2, 3)],           # 4  — c2 above
    [(0, 2)],           # 5  — c0,c2 above
    [(0, 1), (2, 3)],   # 6  — c1,c2 above (saddle)
    [(1, 2)],           # 7  — c0,c1,c2 above
    [(1, 2)],           # 8  — c3 above
    [(0, 3), (1, 2)],   # 9  — c0,c3 above (saddle)
    [(0, 2)],           # 10 — c1,c3 above
    [(2, 3)],           # 11 — c0,c1,c3 above
    [(1, 3)],           # 12 — c2,c3 above
    [(0, 1)],           # 13 — c0,c2,c3 above
    [(0, 3)],           # 14 — c1,c2,c3 above
    [],                 # 15 — all above
]


def generate_contours(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    major_interval: float,
    minor_interval: float,
    grid_cells: int = 150,
) -> Tuple[List[Segment], List[Segment]]:
    """Generate contour line segments from scattered elevation points.

    Args:
        x, y, z: 1-D coordinate arrays (already in output units — US survey ft).
        major_interval: Elevation interval for major contours (e.g. 1.0 ft).
        minor_interval: Elevation interval for minor contours (e.g. 0.25 ft).
        grid_cells: Interpolation grid resolution per axis.

    Returns:
        (major_segments, minor_segments) — lists of ((x1,y1),(x2,y2)) tuples.
    """
    if len(x) < 3:
        logger.warning("Too few GR points (%d) for contours; need ≥ 3", len(x))
        return [], []

    try:
        from scipy.interpolate import griddata
    except ImportError:
        logger.warning("scipy not installed; skipping contour generation")
        return [], []

    x_range = float(x.max() - x.min())
    y_range = float(y.max() - y.min())
    margin = 0.05 * max(x_range, y_range, 1.0)

    xi = np.linspace(x.min() - margin, x.max() + margin, grid_cells + 1)
    yi = np.linspace(y.min() - margin, y.max() + margin, grid_cells + 1)
    xi_g, yi_g = np.meshgrid(xi, yi, indexing="ij")

    zi_g = griddata((x, y), z, (xi_g, yi_g), method="linear")

    z_valid = zi_g[~np.isnan(zi_g)]
    if len(z_valid) == 0:
        return [], []

    z_min, z_max = float(z_valid.min()), float(z_valid.max())
    minor_levels = _contour_levels(z_min, z_max, minor_interval)

    major_segs: List[Segment] = []
    minor_segs: List[Segment] = []

    for level in minor_levels:
        segs = _march_squares(xi, yi, zi_g, level)
        if _is_major(level, major_interval):
            major_segs.extend(segs)
        else:
            minor_segs.extend(segs)

    logger.info(
        "Contours: %d major, %d minor segments (interval %g/%g ft)",
        len(major_segs), len(minor_segs), major_interval, minor_interval,
    )
    return major_segs, minor_segs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contour_levels(z_min: float, z_max: float, interval: float) -> List[float]:
    """Contour levels at multiples of interval that lie within [z_min, z_max]."""
    first = math.ceil(z_min / interval) * interval
    levels: List[float] = []
    level = first
    while level <= z_max + 1e-9 * interval:
        levels.append(level)
        level += interval
    return levels


def _is_major(level: float, major_interval: float) -> bool:
    """True if level is (very nearly) an integer multiple of major_interval."""
    remainder = level % major_interval
    eps = 1e-8 * major_interval
    return remainder < eps or (major_interval - remainder) < eps


def _march_squares(
    xi: np.ndarray,
    yi: np.ndarray,
    zi: np.ndarray,
    level: float,
) -> List[Segment]:
    """Extract line segments at *level* from a regular grid using marching squares."""
    nx, ny = zi.shape
    above = zi > level  # NaN evaluates to False — cells with NaN corners are skipped
    segments: List[Segment] = []

    for i in range(nx - 1):
        for j in range(ny - 1):
            z00 = zi[i, j]
            z10 = zi[i + 1, j]
            z01 = zi[i, j + 1]
            z11 = zi[i + 1, j + 1]

            if np.isnan(z00) or np.isnan(z10) or np.isnan(z01) or np.isnan(z11):
                continue

            case = (
                int(above[i, j])
                | (int(above[i + 1, j]) << 1)
                | (int(above[i, j + 1]) << 2)
                | (int(above[i + 1, j + 1]) << 3)
            )

            for ea, eb in _CASE_SEGS[case]:
                pa = _edge_point(i, j, ea, xi, yi, z00, z10, z01, z11, level)
                pb = _edge_point(i, j, eb, xi, yi, z00, z10, z01, z11, level)
                if pa is not None and pb is not None:
                    segments.append((pa, pb))

    return segments


def _edge_point(
    i: int,
    j: int,
    edge: int,
    xi: np.ndarray,
    yi: np.ndarray,
    z00: float,
    z10: float,
    z01: float,
    z11: float,
    level: float,
) -> Optional[Tuple[float, float]]:
    """Linearly interpolated crossing point on a cell edge."""
    x0, x1 = float(xi[i]), float(xi[i + 1])
    y0, y1 = float(yi[j]), float(yi[j + 1])

    if edge == 0:   # bottom: c0→c1
        dz = z10 - z00
        if dz == 0:
            return None
        t = (level - z00) / dz
        return (x0 + t * (x1 - x0), y0)
    if edge == 1:   # right: c1→c3
        dz = z11 - z10
        if dz == 0:
            return None
        t = (level - z10) / dz
        return (x1, y0 + t * (y1 - y0))
    if edge == 2:   # top: c2→c3
        dz = z11 - z01
        if dz == 0:
            return None
        t = (level - z01) / dz
        return (x0 + t * (x1 - x0), y1)
    if edge == 3:   # left: c0→c2
        dz = z01 - z00
        if dz == 0:
            return None
        t = (level - z00) / dz
        return (x0, y0 + t * (y1 - y0))
    return None
