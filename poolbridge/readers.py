"""File format readers for all Emlid export types.

Supported formats:
    - Emlid Flow CSV (full-attribute, UTF-8 BOM)
    - PENZD CSV (Point, Easting, Northing, Z, Description)
    - KML (Emlid Flow Google Earth export)
    - Shapefile (.shp + sidecar files, or .zip archive)
    - Emlid DXF (single-layer point dump — imported and re-layered)
"""

import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_CSV_ENCODING = "utf-8-sig"

# Columns that must exist in the normalised output
STANDARD_COLUMNS = ["Name", "Code", "Easting", "Northing", "Elevation", "Description"]

# KML namespace
_KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def read_file(path: str) -> pd.DataFrame:
    """Detect format and load an Emlid export file into a standard DataFrame.

    All readers return a DataFrame with at minimum:
        Name, Code, Easting, Northing, Elevation, Description
    and optionally:
        Longitude, Latitude, Origin

    Args:
        path: Path to the input file (.csv, .kml, .shp, .zip, .dxf).

    Returns:
        Normalised survey DataFrame.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the format cannot be determined or parsed.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = p.suffix.lower()
    if suffix == ".kml":
        return read_kml(path)
    if suffix == ".shp":
        return read_shapefile(path)
    if suffix == ".zip":
        return read_shapefile_zip(path)
    if suffix == ".dxf":
        return read_emlid_dxf(path)
    if suffix in (".csv", ".txt"):
        return _auto_csv(path)

    raise ValueError(
        f"Unrecognised file extension '{suffix}'. "
        f"Supported: .csv, .txt (PENZD), .kml, .shp, .zip, .dxf"
    )


# ---------------------------------------------------------------------------
# CSV variants
# ---------------------------------------------------------------------------

def read_emlid_csv(path: str) -> pd.DataFrame:
    """Load a full-attribute Emlid Flow CSV export.

    Args:
        path: Path to the CSV file.

    Returns:
        Normalised DataFrame.
    """
    df = pd.read_csv(path, encoding=_CSV_ENCODING, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df.apply(lambda col: col.str.strip() if col.dtype == object else col)
    for col in ("Easting", "Northing", "Elevation", "Longitude", "Latitude",
                "Ellipsoidal height"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info("Loaded %d points from Emlid CSV: %s", len(df), path)
    return _ensure_standard_columns(df)


def read_penzd_csv(path: str) -> pd.DataFrame:
    """Load a PENZD CSV (Point, Easting, Northing, Z, Description).

    Accepts common header variants: Point/Name, Z/Elevation/Elev,
    Description/Desc/Note.  The Code column is derived from the point
    name if it follows the pattern CODE or CODE-N (e.g. 'HC-1').

    Args:
        path: Path to the PENZD CSV file.

    Returns:
        Normalised DataFrame.
    """
    df = pd.read_csv(path, encoding=_CSV_ENCODING, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df.apply(lambda col: col.str.strip() if col.dtype == object else col)

    # Normalise column names
    rename = {}
    for col in df.columns:
        cl = col.lower()
        if cl in ("point", "pt", "id") and "Name" not in df.columns:
            rename[col] = "Name"
        elif cl in ("z", "elev", "elevation", "height") and "Elevation" not in df.columns:
            rename[col] = "Elevation"
        elif cl in ("desc", "description", "note", "notes") and "Description" not in df.columns:
            rename[col] = "Description"
    df = df.rename(columns=rename)

    for col in ("Easting", "Northing", "Elevation"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Derive Code from Name if no Code column present
    if "Code" not in df.columns:
        df["Code"] = df.get("Name", pd.Series([""] * len(df))).apply(_code_from_name)

    # PENZD has no lat/lon — mark as Local origin so reprojection is skipped
    if "Origin" not in df.columns:
        df["Origin"] = "Local"

    logger.info("Loaded %d points from PENZD CSV: %s", len(df), path)
    return _ensure_standard_columns(df)


def _auto_csv(path: str) -> pd.DataFrame:
    """Detect CSV subtype and route to the appropriate reader."""
    with open(path, encoding=_CSV_ENCODING, errors="replace") as fh:
        header = fh.readline().lower()

    # PENZD if it lacks 'code' and has typical PENZD-style columns
    has_code = "code" in header
    has_emlid_cols = "longitude" in header or "latitude" in header or "ellipsoidal" in header

    if not has_code and not has_emlid_cols:
        logger.info("Detected PENZD CSV format: %s", path)
        return read_penzd_csv(path)

    return read_emlid_csv(path)


# ---------------------------------------------------------------------------
# KML
# ---------------------------------------------------------------------------

def read_kml(path: str) -> pd.DataFrame:
    """Load an Emlid Flow KML export.

    Extracts all Placemark/Point features.  The placemark <name> becomes
    the point Name, and the <description> is used as Description (and as
    Code if it looks like a survey code word).

    Args:
        path: Path to the .kml file.

    Returns:
        Normalised DataFrame.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    # Handle both namespaced and bare KML
    ns = ""
    tag = root.tag
    if tag.startswith("{"):
        ns = tag.split("}")[0] + "}"

    rows = []
    for pm in root.iter(f"{ns}Placemark"):
        name_el = pm.find(f"{ns}name")
        desc_el = pm.find(f"{ns}description")
        point_el = pm.find(f"{ns}Point")
        if point_el is None:
            continue  # skip non-point features

        coords_el = point_el.find(f"{ns}coordinates")
        if coords_el is None or not coords_el.text:
            continue

        parts = coords_el.text.strip().split(",")
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 else 0.0
        except (ValueError, IndexError):
            continue

        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""

        rows.append({
            "Name": name,
            "Code": _code_from_name(name) if desc == "" else _code_from_name(desc) or _code_from_name(name),
            "Longitude": lon,
            "Latitude": lat,
            "Easting": float("nan"),
            "Northing": float("nan"),
            "Elevation": alt,
            "Description": desc,
            "Origin": "Global",
        })

    df = pd.DataFrame(rows)
    logger.info("Loaded %d points from KML: %s", len(df), path)
    return _ensure_standard_columns(df)


# ---------------------------------------------------------------------------
# Shapefile
# ---------------------------------------------------------------------------

def read_shapefile(path: str) -> pd.DataFrame:
    """Load an Emlid Flow Shapefile export (.shp with .dbf sidecar).

    Emlid shapefiles carry attributes matching the CSV column names
    (Name, Code, Easting, Northing, Elevation, etc.) so they map directly.

    Args:
        path: Path to the .shp file.  The .dbf and .shx must be alongside it.

    Returns:
        Normalised DataFrame.
    """
    try:
        import shapefile
    except ImportError as exc:
        raise ImportError(
            "pyshp is required for Shapefile support. "
            "Install it with: pip install pyshp"
        ) from exc

    sf = shapefile.Reader(path)
    fields = [f[0] for f in sf.fields[1:]]  # skip DeletionFlag
    rows = []
    for sr in sf.shapeRecords():
        record = dict(zip(fields, sr.record))
        geom = sr.shape
        if geom.shapeType == 1:  # Point
            x, y = geom.points[0]
            z = geom.z[0] if hasattr(geom, "z") and geom.z else 0.0
        elif geom.shapeType == 11:  # PointZ
            x, y = geom.points[0]
            z = geom.z[0] if geom.z else 0.0
        else:
            continue

        # If shapefile has E/N attributes, prefer them; otherwise use geometry X/Y
        easting = float(record.get("Easting", x) or x)
        northing = float(record.get("Northing", y) or y)
        elevation = float(record.get("Elevation", z) or z)
        lon = float(record["Longitude"]) if record.get("Longitude") else float("nan")
        lat = float(record["Latitude"]) if record.get("Latitude") else float("nan")

        rows.append({
            "Name": str(record.get("Name", record.get("name", ""))).strip(),
            "Code": str(record.get("Code", record.get("code", ""))).strip(),
            "Easting": easting,
            "Northing": northing,
            "Elevation": elevation,
            "Description": str(record.get("Description", record.get("description", ""))).strip(),
            "Longitude": lon,
            "Latitude": lat,
            "Origin": str(record.get("Origin", "Global")).strip(),
        })

    df = pd.DataFrame(rows)
    logger.info("Loaded %d points from Shapefile: %s", len(df), path)
    return _ensure_standard_columns(df)


def read_shapefile_zip(path: str) -> pd.DataFrame:
    """Load a Shapefile from a ZIP archive containing .shp/.dbf/.shx files.

    Args:
        path: Path to the .zip file.

    Returns:
        Normalised DataFrame.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(tmpdir)
        shp_files = list(Path(tmpdir).rglob("*.shp"))
        if not shp_files:
            raise ValueError(f"No .shp file found inside ZIP archive: {path}")
        return read_shapefile(str(shp_files[0]))


# ---------------------------------------------------------------------------
# Emlid DXF import
# ---------------------------------------------------------------------------

def read_emlid_dxf(path: str) -> pd.DataFrame:
    """Import an Emlid-generated DXF (single-layer, label-less point dump).

    Extracts POINT entities and any TEXT entities nearby.  Since Emlid DXF
    carries no code information per point, the Code is set to the layer name
    of each POINT entity (which is "0" in most Emlid exports) unless a TEXT
    entity within 0.5 drawing units matches the point.

    Args:
        path: Path to the .dxf file.

    Returns:
        Normalised DataFrame.  Longitude/Latitude will be NaN (DXF has no
        geographic coordinates); Origin is set to "Local" so reprojection
        is skipped.
    """
    import ezdxf

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    # Collect all TEXT entities for nearby-name matching
    texts = []
    for ent in msp:
        if ent.dxftype() == "TEXT":
            try:
                texts.append({
                    "x": ent.dxf.insert.x,
                    "y": ent.dxf.insert.y,
                    "text": ent.dxf.text.strip(),
                })
            except Exception:
                pass

    rows = []
    counter = 1
    for ent in msp:
        if ent.dxftype() != "POINT":
            continue
        try:
            x = ent.dxf.location.x
            y = ent.dxf.location.y
            z = ent.dxf.location.z
        except Exception:
            continue

        layer = ent.dxf.layer.strip() if ent.dxf.hasattr("layer") else "0"
        code = layer if layer not in ("0", "") else ""

        # Look for a TEXT within 0.5 units to use as the point name
        name = _nearest_text(x, y, texts, threshold=0.5)
        if not name:
            name = f"PT{counter}"
        counter += 1

        rows.append({
            "Name": name,
            "Code": code or _code_from_name(name),
            "Easting": x,
            "Northing": y,
            "Elevation": z,
            "Description": "",
            "Longitude": float("nan"),
            "Latitude": float("nan"),
            "Origin": "Local",
        })

    df = pd.DataFrame(rows)
    logger.info("Loaded %d points from Emlid DXF: %s", len(df), path)
    return _ensure_standard_columns(df)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_standard_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add any missing standard columns with sensible defaults."""
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ("Name", "Code", "Description") else float("nan")
    return df


_CODE_RE = re.compile(r"^([A-Za-z]{1,6})")


def _code_from_name(name: str) -> str:
    """Extract a feature code from a point name like 'HC-1' → 'HC'."""
    if not name:
        return ""
    m = _CODE_RE.match(name.strip())
    return m.group(1).upper() if m else ""


def _nearest_text(
    x: float,
    y: float,
    texts: list,
    threshold: float = 0.5,
) -> Optional[str]:
    """Return the text of the nearest TEXT entity within threshold, or None."""
    best_dist = threshold + 1
    best_text = None
    for t in texts:
        dist = ((t["x"] - x) ** 2 + (t["y"] - y) ** 2) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_text = t["text"]
    return best_text if best_dist <= threshold else None
