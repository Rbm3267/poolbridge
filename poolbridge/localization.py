"""Coordinate reprojection and 2D localization (rigid-body / Helmert transforms)."""

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from pyproj import Transformer

logger = logging.getLogger(__name__)

# Meters → US survey feet exact conversion factor (3937/1200)
METERS_TO_US_SURVEY_FEET = 3937.0 / 1200.0


# ---------------------------------------------------------------------------
# CRS reprojection
# ---------------------------------------------------------------------------

def reproject_dataframe(
    df: pd.DataFrame,
    source_crs: str,
    target_crs: str,
) -> pd.DataFrame:
    """Reproject Easting/Northing columns from source_crs to target_crs.

    When source_crs is EPSG:4326 (WGS84), the Longitude and Latitude columns
    are used as input coordinates. Otherwise Easting/Northing are used directly.

    Args:
        df: Survey DataFrame with Easting, Northing (and optionally Longitude,
            Latitude) columns.
        source_crs: EPSG string for the input coordinate system (e.g. 'EPSG:4326').
        target_crs: EPSG string for the output coordinate system (e.g. 'EPSG:32614').

    Returns:
        DataFrame with Easting and Northing columns replaced by reprojected values.
    """
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    df = df.copy()

    if source_crs.upper() in ("EPSG:4326", "WGS84") and "Longitude" in df.columns and "Latitude" in df.columns:
        lons = pd.to_numeric(df["Longitude"], errors="coerce")
        lats = pd.to_numeric(df["Latitude"], errors="coerce")
        east, north = transformer.transform(lons.values, lats.values)
    else:
        east_in = pd.to_numeric(df["Easting"], errors="coerce")
        north_in = pd.to_numeric(df["Northing"], errors="coerce")
        east, north = transformer.transform(east_in.values, north_in.values)

    df["Easting"] = east
    df["Northing"] = north
    logger.info("Reprojected %d points from %s to %s", len(df), source_crs, target_crs)
    return df


# ---------------------------------------------------------------------------
# Two-point rigid-body localization
# ---------------------------------------------------------------------------

def two_point_transform(
    src_pts: List[Tuple[float, float]],
    tgt_pts: List[Tuple[float, float]],
) -> Dict[str, Any]:
    """Compute a 2D similarity transform from exactly 2 control point pairs.

    Solves for rotation, scale, and translation so that each source point maps
    to its corresponding target point exactly.

    Args:
        src_pts: List of 2 (easting, northing) tuples — measured survey coords.
        tgt_pts: List of 2 (easting, northing) tuples — known/design coords.

    Returns:
        Dict with keys:
            theta (float): Rotation angle in radians.
            scale (float): Scale factor (ideally ≈1.0 for RTK surveys).
            tx (float): X translation.
            ty (float): Y translation.
            a (float): scale * cos(theta).
            b (float): scale * sin(theta).
            residuals (list[float]): Per-point residual distances.
            rms (float): Root-mean-square residual.
    """
    if len(src_pts) != 2 or len(tgt_pts) != 2:
        raise ValueError("two_point_transform requires exactly 2 point pairs")

    x1s, y1s = src_pts[0]
    x2s, y2s = src_pts[1]
    x1t, y1t = tgt_pts[0]
    x2t, y2t = tgt_pts[1]

    dx_s = x2s - x1s
    dy_s = y2s - y1s
    dx_t = x2t - x1t
    dy_t = y2t - y1t

    len_s = math.sqrt(dx_s ** 2 + dy_s ** 2)
    len_t = math.sqrt(dx_t ** 2 + dy_t ** 2)

    if len_s < 1e-9:
        raise ValueError(
            "Source control points are coincident — cannot compute transform."
        )

    angle_s = math.atan2(dy_s, dx_s)
    angle_t = math.atan2(dy_t, dx_t)
    theta = angle_t - angle_s
    scale = len_t / len_s

    a = scale * math.cos(theta)
    b = scale * math.sin(theta)

    tx = x1t - (a * x1s - b * y1s)
    ty = y1t - (b * x1s + a * y1s)

    residuals, rms = _compute_residuals(src_pts, tgt_pts, a, b, tx, ty)

    if abs(scale - 1.0) > 0.001:
        logger.warning(
            "Two-point scale factor is %.6f (expected ≈1.0). "
            "Check that both coordinate systems use the same units.",
            scale,
        )

    logger.info(
        "Two-point localization: theta=%.4f°, scale=%.6f, RMS=%.4f",
        math.degrees(theta),
        scale,
        rms,
    )

    return {"theta": theta, "scale": scale, "tx": tx, "ty": ty, "a": a, "b": b,
            "residuals": residuals, "rms": rms}


# ---------------------------------------------------------------------------
# Least-squares Helmert (N ≥ 2 control points)
# ---------------------------------------------------------------------------

def helmert_transform(
    src_pts: List[Tuple[float, float]],
    tgt_pts: List[Tuple[float, float]],
) -> Dict[str, Any]:
    """Compute a least-squares 2D similarity (Helmert) transform for N ≥ 2 points.

    The transform model is:
        x_t = a*x_s - b*y_s + tx
        y_t = b*x_s + a*y_s + ty
    where a = scale*cos(theta), b = scale*sin(theta).

    Args:
        src_pts: List of N (easting, northing) tuples — measured survey coords.
        tgt_pts: List of N (easting, northing) tuples — known/design coords.

    Returns:
        Same dict structure as two_point_transform, plus:
            residual_vectors (list[tuple]): Per-point (dx, dy) residuals.
    """
    if len(src_pts) < 2:
        raise ValueError("helmert_transform requires at least 2 control points")
    if len(src_pts) != len(tgt_pts):
        raise ValueError("src_pts and tgt_pts must have the same length")

    n = len(src_pts)
    A = np.zeros((2 * n, 4))
    b_vec = np.zeros(2 * n)

    for i, ((xs, ys), (xt, yt)) in enumerate(zip(src_pts, tgt_pts)):
        A[2 * i] = [xs, -ys, 1, 0]
        b_vec[2 * i] = xt
        A[2 * i + 1] = [ys, xs, 0, 1]
        b_vec[2 * i + 1] = yt

    params, _, _, _ = np.linalg.lstsq(A, b_vec, rcond=None)
    a, b, tx, ty = float(params[0]), float(params[1]), float(params[2]), float(params[3])

    scale = math.sqrt(a ** 2 + b ** 2)
    theta = math.atan2(b, a)

    residuals, rms = _compute_residuals(src_pts, tgt_pts, a, b, tx, ty)

    residual_vectors = []
    for (xs, ys), (xt, yt) in zip(src_pts, tgt_pts):
        xc = a * xs - b * ys + tx
        yc = b * xs + a * ys + ty
        residual_vectors.append((xc - xt, yc - yt))

    if abs(scale - 1.0) > 0.001:
        logger.warning(
            "Helmert scale factor is %.6f (expected ≈1.0). "
            "Check coordinate system units.",
            scale,
        )

    logger.info(
        "Helmert localization: theta=%.4f°, scale=%.6f, RMS=%.4f, N=%d points",
        math.degrees(theta),
        scale,
        rms,
        n,
    )

    return {
        "theta": theta, "scale": scale, "tx": tx, "ty": ty, "a": a, "b": b,
        "residuals": residuals, "rms": rms, "residual_vectors": residual_vectors,
    }


def apply_transform(
    x: float,
    y: float,
    transform: Dict[str, Any],
) -> Tuple[float, float]:
    """Apply a 2D similarity transform to a single point.

    Args:
        x: Input easting.
        y: Input northing.
        transform: Dict returned by two_point_transform or helmert_transform.

    Returns:
        Transformed (x, y) tuple.
    """
    a = transform["a"]
    b = transform["b"]
    tx = transform["tx"]
    ty = transform["ty"]
    return a * x - b * y + tx, b * x + a * y + ty


def apply_transform_dataframe(
    df: pd.DataFrame,
    transform: Dict[str, Any],
) -> pd.DataFrame:
    """Apply a 2D similarity transform to all rows of a DataFrame.

    Args:
        df: DataFrame with 'Easting' and 'Northing' columns.
        transform: Dict returned by two_point_transform or helmert_transform.

    Returns:
        DataFrame with updated Easting/Northing columns.
    """
    df = df.copy()
    east = pd.to_numeric(df["Easting"], errors="coerce").values
    north = pd.to_numeric(df["Northing"], errors="coerce").values
    a, b = transform["a"], transform["b"]
    tx, ty = transform["tx"], transform["ty"]
    df["Easting"] = a * east - b * north + tx
    df["Northing"] = b * east + a * north + ty
    return df


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

def meters_to_feet(df: pd.DataFrame) -> pd.DataFrame:
    """Convert Easting, Northing, and Elevation columns from meters to US survey feet.

    Args:
        df: DataFrame with numeric Easting, Northing, Elevation columns.

    Returns:
        DataFrame with converted columns.
    """
    df = df.copy()
    for col in ("Easting", "Northing", "Elevation"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce") * METERS_TO_US_SURVEY_FEET
    logger.debug("Converted coordinates from meters to US survey feet")
    return df


# ---------------------------------------------------------------------------
# Control point extraction helpers
# ---------------------------------------------------------------------------

def extract_control_coords(
    df: pd.DataFrame,
    control_points: List[Dict[str, Any]],
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """Pull source (measured) and target (known) coordinates from config.

    Args:
        df: Survey DataFrame indexed or searchable by 'Name'.
        control_points: List of dicts with 'name', 'known_easting',
            'known_northing' keys.

    Returns:
        (src_pts, tgt_pts) — parallel lists of (easting, northing) tuples.
    """
    name_index = df.set_index(df["Name"].astype(str).str.strip())
    src_pts: List[Tuple[float, float]] = []
    tgt_pts: List[Tuple[float, float]] = []

    for cp in control_points:
        name = str(cp["name"]).strip()
        row = name_index.loc[name]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        src_pts.append((float(row["Easting"]), float(row["Northing"])))
        tgt_pts.append((float(cp["known_easting"]), float(cp["known_northing"])))

    return src_pts, tgt_pts


def format_localization_report(
    control_points: List[Dict[str, Any]],
    src_pts: List[Tuple[float, float]],
    tgt_pts: List[Tuple[float, float]],
    transform: Dict[str, Any],
    unit_label: str = "ft",
) -> str:
    """Return a human-readable localization residual report.

    Args:
        control_points: Config list of control point dicts.
        src_pts: Measured source coordinates.
        tgt_pts: Known target coordinates.
        transform: Result from two_point_transform or helmert_transform.
        unit_label: Unit suffix for display (default 'ft').

    Returns:
        Multi-line string report.
    """
    lines = [
        "--- Localization Report ---",
        f"  Method : {'Two-Point' if len(src_pts) == 2 else 'Helmert LS'}",
        f"  Points : {len(src_pts)}",
        f"  Rotation: {math.degrees(transform['theta']):.4f}°",
        f"  Scale   : {transform['scale']:.6f}",
        f"  RMS     : {transform['rms']:.4f} {unit_label}",
        "",
        f"  {'Name':<12} {'Src E':>12} {'Src N':>12} {'Tgt E':>12} {'Tgt N':>12} {'Resid':>8}",
        "  " + "-" * 64,
    ]
    for i, cp in enumerate(control_points):
        name = cp.get("name", f"CP{i+1}")
        se, sn = src_pts[i]
        te, tn = tgt_pts[i]
        res = transform["residuals"][i]
        lines.append(
            f"  {name:<12} {se:>12.3f} {sn:>12.3f} "
            f"{te:>12.3f} {tn:>12.3f} {res:>8.4f}"
        )
    lines.append("--- End Report ---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_residuals(
    src_pts: List[Tuple[float, float]],
    tgt_pts: List[Tuple[float, float]],
    a: float,
    b: float,
    tx: float,
    ty: float,
) -> Tuple[List[float], float]:
    """Compute per-point residuals and RMS for a given transform."""
    residuals = []
    for (xs, ys), (xt, yt) in zip(src_pts, tgt_pts):
        xc = a * xs - b * ys + tx
        yc = b * xs + a * ys + ty
        residuals.append(math.sqrt((xc - xt) ** 2 + (yc - yt) ** 2))
    rms = math.sqrt(sum(r ** 2 for r in residuals) / len(residuals))
    return residuals, rms
