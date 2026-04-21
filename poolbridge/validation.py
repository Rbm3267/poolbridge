"""Input validation, data quality checks, and datum mismatch warnings."""

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"Name", "Code", "Easting", "Northing", "Elevation"}
OPTIONAL_COLUMNS = {"Description", "Longitude", "Latitude", "Ellipsoidal height", "Origin"}

# Threshold below which elevations are flagged as potentially ellipsoidal
_ELLIPSOIDAL_WARNING_THRESHOLD = -10.0


class ValidationError(Exception):
    """Raised for unrecoverable input errors."""


class ValidationWarning(UserWarning):
    """Issued for non-fatal data quality issues."""


def validate_dataframe(df: pd.DataFrame) -> List[str]:
    """Check a loaded Emlid CSV dataframe for required columns and data issues.

    Args:
        df: DataFrame loaded from an Emlid CSV export.

    Returns:
        List of warning message strings (empty if no warnings).

    Raises:
        ValidationError: If required columns are missing or data is unusable.
    """
    warnings: List[str] = []

    _check_required_columns(df)
    warnings.extend(_check_duplicates(df))
    warnings.extend(_check_elevation_datum(df))
    warnings.extend(_check_coordinate_range(df))

    return warnings


def validate_control_points(
    df: pd.DataFrame,
    control_points: List[Dict[str, Any]],
) -> List[str]:
    """Validate that localization control points exist in the dataframe.

    Args:
        df: Survey point dataframe.
        control_points: List of dicts with at least 'name' key from config.

    Returns:
        List of warning message strings.

    Raises:
        ValidationError: If fewer than 2 control points are present or if named
            control points cannot be found in the dataframe.
    """
    warnings: List[str] = []

    if len(control_points) < 2:
        raise ValidationError(
            f"Localization requires at least 2 control points; "
            f"got {len(control_points)}. Add control_points to your config."
        )

    names_in_df = set(df["Name"].astype(str).str.strip())
    missing = []
    for cp in control_points:
        name = str(cp.get("name", "")).strip()
        if not name:
            raise ValidationError("A control point entry is missing its 'name' field.")
        if name not in names_in_df:
            missing.append(name)

    if missing:
        raise ValidationError(
            f"Control point(s) not found in CSV: {missing}. "
            f"Check that point names match exactly (case-sensitive)."
        )

    src_pts = _extract_source_coords(df, control_points)
    warnings.extend(_check_control_point_separation(src_pts, control_points))

    return warnings


def validate_transform_result(
    transform: Dict[str, Any],
    max_rms_warning_ft: float = 0.1,
) -> List[str]:
    """Check localization residuals and warn if RMS is high.

    Args:
        transform: Result dict from localization module.
        max_rms_warning_ft: RMS threshold (in feet) above which a warning is issued.

    Returns:
        List of warning message strings.
    """
    warnings: List[str] = []
    rms = transform.get("rms", 0.0)
    if rms > max_rms_warning_ft:
        warnings.append(
            f"Localization RMS error is {rms:.4f} ft — this is higher than the "
            f"{max_rms_warning_ft:.3f} ft threshold. Check your control point "
            f"coordinates for typos or blunders."
        )
    return warnings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_required_columns(df: pd.DataFrame) -> None:
    """Raise ValidationError if any required columns are absent."""
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValidationError(
            f"CSV is missing required column(s): {sorted(missing)}. "
            f"Expected columns: {sorted(REQUIRED_COLUMNS)}."
        )


def _check_duplicates(df: pd.DataFrame) -> List[str]:
    """Warn about duplicate point names."""
    warnings: List[str] = []
    dupes = df["Name"].astype(str).str.strip()
    dupes = dupes[dupes.duplicated(keep=False)]
    if not dupes.empty:
        names = sorted(dupes.unique().tolist())
        warnings.append(
            f"Duplicate point name(s) found: {names}. "
            f"All instances are kept; downstream operations may be unpredictable."
        )
    return warnings


def _check_elevation_datum(df: pd.DataFrame) -> List[str]:
    """Warn if elevations look like raw ellipsoidal heights (negative values)."""
    warnings: List[str] = []
    elevations = pd.to_numeric(df["Elevation"], errors="coerce").dropna()
    if elevations.empty:
        warnings.append("Elevation column contains no numeric values.")
        return warnings

    min_elev = elevations.min()
    if min_elev < _ELLIPSOIDAL_WARNING_THRESHOLD:
        warnings.append(
            f"Minimum elevation is {min_elev:.3f} m. Negative or near-zero "
            f"elevations may indicate ellipsoidal height without a geoid correction "
            f"(EGM96/GEOID18). Verify your Emlid project datum settings. "
            f"Use z_datum.offset in config to apply a manual correction."
        )

    if "Ellipsoidal height" in df.columns:
        ell = pd.to_numeric(df["Ellipsoidal height"], errors="coerce").dropna()
        if not ell.empty and not elevations.empty:
            diff = (elevations - ell).abs().mean()
            if diff < 0.01:
                warnings.append(
                    "Elevation and Ellipsoidal height columns are nearly identical. "
                    "Your project may be using ellipsoidal heights instead of "
                    "orthometric (geoid-corrected) elevations."
                )

    return warnings


def _check_coordinate_range(df: pd.DataFrame) -> List[str]:
    """Warn if Easting/Northing values look like raw WGS84 degrees."""
    warnings: List[str] = []
    easting = pd.to_numeric(df["Easting"], errors="coerce").dropna()
    northing = pd.to_numeric(df["Northing"], errors="coerce").dropna()

    if easting.empty or northing.empty:
        warnings.append("Easting or Northing column contains no numeric values.")
        return warnings

    e_range = easting.max() - easting.min()
    n_range = northing.max() - northing.min()

    # If range is less than 1 unit, might be lat/lon degrees with small survey area
    if e_range < 1.0 and n_range < 1.0:
        warnings.append(
            f"Easting range ({e_range:.6f}) and Northing range ({n_range:.6f}) "
            f"are less than 1 unit. If your CSV stores geographic coordinates "
            f"(degrees) in E/N columns rather than projected meters, set "
            f"coordinate_system.source_crs to 'EPSG:4326' and specify a "
            f"target_crs in your config."
        )

    return warnings


def _extract_source_coords(
    df: pd.DataFrame,
    control_points: List[Dict[str, Any]],
) -> List[Tuple[float, float]]:
    """Return list of (easting, northing) for each named control point."""
    idx = df.set_index(df["Name"].astype(str).str.strip())
    coords = []
    for cp in control_points:
        name = str(cp["name"]).strip()
        row = idx.loc[name]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        coords.append((float(row["Easting"]), float(row["Northing"])))
    return coords


def _check_control_point_separation(
    src_pts: List[Tuple[float, float]],
    control_points: List[Dict[str, Any]],
) -> List[str]:
    """Warn if two control points are suspiciously close together."""
    warnings: List[str] = []
    for i in range(len(src_pts)):
        for j in range(i + 1, len(src_pts)):
            x1, y1 = src_pts[i]
            x2, y2 = src_pts[j]
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            n1 = control_points[i].get("name", f"CP{i+1}")
            n2 = control_points[j].get("name", f"CP{j+1}")
            if dist < 1.0:
                warnings.append(
                    f"Control points '{n1}' and '{n2}' are only {dist:.4f} m apart. "
                    f"Use widely separated, stable monuments for best localization accuracy."
                )
    return warnings
