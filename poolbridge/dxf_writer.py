"""DXF file generation with AIA NCS layers, smart features, and Pool Studio settings."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf.document import Drawing
from ezdxf.layouts import Modelspace

import pandas as pd

from poolbridge.config import collect_layers, get_feature_config

logger = logging.getLogger(__name__)

# Pool Studio requires $INSUNITS=2 (decimal feet), $MEASUREMENT=0 (imperial),
# $PDMODE=35 (X+circle), $PDSIZE=0.5
_INSUNITS_DECIMAL_FEET = 2
_MEASUREMENT_IMPERIAL = 0
_PDMODE_X_CIRCLE = 35
_DEFAULT_PDSIZE = 0.5
_DEFAULT_TEXT_HEIGHT = 0.5
_DEFAULT_TEXT_OFFSET = 0.3  # feet above point for label placement

# Regex patterns for extracting tree drip diameter from Description
_DIAMETER_PATTERNS = [
    re.compile(r"D\s*=\s*([\d.]+)\s*'", re.IGNORECASE),   # D=12' or D = 12'
    re.compile(r"D\s*=\s*([\d.]+)\s*ft", re.IGNORECASE),  # D=12ft
    re.compile(r"D\s*=\s*([\d.]+)\s*m\b", re.IGNORECASE), # D=3.66m (converted)
    re.compile(r"DIA\s*[=:]\s*([\d.]+)", re.IGNORECASE),  # DIA=12 or DIA:12
    re.compile(r"([\d.]+)\s*'\s*dia", re.IGNORECASE),     # 12' dia
]


class DXFWriter:
    """Builds a DXF document from a processed survey DataFrame.

    Args:
        config: Full poolbridge configuration dictionary.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.output_cfg = config.get("output", {})
        self.text_height = float(self.output_cfg.get("text_height", _DEFAULT_TEXT_HEIGHT))
        self.pdsize = float(self.output_cfg.get("pdsize", _DEFAULT_PDSIZE))
        self.pdmode = int(self.output_cfg.get("pdmode", _PDMODE_X_CIRCLE))

    def write(self, df: pd.DataFrame, output_path: str) -> None:
        """Generate and save a DXF file from a processed survey DataFrame.

        Args:
            df: DataFrame with columns Name, Code, Easting, Northing, Elevation,
                Description (and optionally base_code, code_number).
            output_path: Destination file path (should end in .dxf).
        """
        doc = self._init_document()
        msp = doc.modelspace()
        self._create_layers(doc)
        self._write_points(df, msp)
        self._write_smart_features(df, msp)
        doc.saveas(output_path)
        logger.info("DXF written to %s (%d points)", output_path, len(df))

    # ------------------------------------------------------------------
    # Document initialisation
    # ------------------------------------------------------------------

    def _init_document(self) -> Drawing:
        version = self.output_cfg.get("dxf_version", "R2010")
        doc = ezdxf.new(version)
        doc.header["$INSUNITS"] = _INSUNITS_DECIMAL_FEET
        doc.header["$MEASUREMENT"] = _MEASUREMENT_IMPERIAL
        doc.header["$PDMODE"] = self.pdmode
        doc.header["$PDSIZE"] = self.pdsize
        doc.header["$LTSCALE"] = 0.5
        doc.header["$DIMSCALE"] = 1.0
        return doc

    def _create_layers(self, doc: Drawing) -> None:
        layers = collect_layers(self.config)
        for layer_name, aci_color in layers.items():
            if layer_name not in doc.layers:
                doc.layers.add(layer_name, color=aci_color)

    # ------------------------------------------------------------------
    # Point and label writing
    # ------------------------------------------------------------------

    def _write_points(self, df: pd.DataFrame, msp: Modelspace) -> None:
        for _, row in df.iterrows():
            code = str(row.get("base_code", row.get("Code", ""))).strip()
            feat_cfg = get_feature_config(self.config, code)
            layer = feat_cfg.get("layer", "V-NODE")
            color = feat_cfg.get("color", 7)

            try:
                x = float(row["Easting"])
                y = float(row["Northing"])
                z = float(row["Elevation"])
            except (ValueError, TypeError):
                logger.warning("Skipping point '%s': non-numeric coordinates", row.get("Name", "?"))
                continue

            # Point entity
            msp.add_point(
                (x, y, z),
                dxfattribs={"layer": layer, "color": color},
            )

            # Label on V-NODE-TEXT (or layer-specific text layer)
            self._write_label(msp, row, x, y, z, feat_cfg)

    def _write_label(
        self,
        msp: Modelspace,
        row: pd.Series,
        x: float,
        y: float,
        z: float,
        feat_cfg: Dict[str, Any],
    ) -> None:
        name = str(row.get("Name", "")).strip()
        description = str(row.get("Description", "")).strip()
        label_elevation = feat_cfg.get("label_elevation", False)
        label_prefix = feat_cfg.get("label_prefix", "")

        # Build label text
        if label_elevation:
            elev_str = f"{z:.2f}"
            label = f"{label_prefix}{elev_str}" if label_prefix else f"{name} {elev_str}"
        else:
            label = name

        if not label:
            return

        text_layer = "V-NODE-TEXT"
        msp.add_text(
            label,
            dxfattribs={
                "layer": text_layer,
                "height": self.text_height,
                "insert": (x + _DEFAULT_TEXT_OFFSET, y + _DEFAULT_TEXT_OFFSET, z),
                "color": feat_cfg.get("color", 7),
            },
        )

    # ------------------------------------------------------------------
    # Smart features
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_by_code(df: pd.DataFrame, code: str) -> pd.DataFrame:
        """Return rows whose base_code (or Code) matches *code*."""
        if "base_code" in df.columns:
            return df[df["base_code"].astype(str).str.strip() == code]
        return df[df["Code"].astype(str).str.strip() == code]

    def _write_smart_features(self, df: pd.DataFrame, msp: Modelspace) -> None:
        self._draw_tree_circles(df, msp)
        self._auto_connect_sequence(df, msp, base_code="PC", layer="V-PROP", close=True)
        self._auto_connect_sequence(df, msp, base_code="HC", layer="V-BLDG", close=True)
        self._auto_connect_sequence(df, msp, base_code="EB", layer="V-EASEMENT", close=True)
        self._auto_connect_sequence(df, msp, base_code="SB", layer="V-SETBACK", close=True)
        self._draw_elevation_callouts(df, msp)
        self._draw_contours(df, msp)

    def _draw_tree_circles(self, df: pd.DataFrame, msp: Modelspace) -> None:
        tree_rows = df[df.get("base_code", df["Code"]).astype(str).str.strip() == "TR"]
        if hasattr(df, "loc") and "base_code" in df.columns:
            tree_rows = df[df["base_code"].astype(str).str.strip() == "TR"]
        else:
            tree_rows = df[df["Code"].astype(str).str.strip() == "TR"]

        feat_cfg = get_feature_config(self.config, "TR")
        if not feat_cfg.get("draw_drip_circle", True):
            return

        layer = feat_cfg.get("layer", "V-PLNT-TREE")
        color = feat_cfg.get("color", 3)

        for _, row in tree_rows.iterrows():
            desc = str(row.get("Description", "")).strip()
            radius = _parse_drip_radius_ft(desc)
            if radius is None:
                logger.debug("Tree '%s': no diameter found in Description '%s'", row.get("Name"), desc)
                continue

            try:
                x = float(row["Easting"])
                y = float(row["Northing"])
            except (ValueError, TypeError):
                continue

            msp.add_circle(
                (x, y),
                radius=radius,
                dxfattribs={"layer": layer, "color": color},
            )
            logger.debug("Drew drip circle r=%.2f ft for tree '%s'", radius, row.get("Name"))

    def _auto_connect_sequence(
        self,
        df: pd.DataFrame,
        msp: Modelspace,
        base_code: str,
        layer: str,
        close: bool = True,
    ) -> None:
        """Connect sequentially numbered points (PC-1, PC-2, …) with a polyline."""
        if "base_code" in df.columns:
            mask = df["base_code"].astype(str).str.strip() == base_code
        else:
            mask = df["Code"].astype(str).str.strip().str.startswith(base_code)
        subset = df[mask].copy()

        if len(subset) < 2:
            return

        # Sort by code number if present; otherwise by Name
        if "code_number" in subset.columns:
            subset = subset.sort_values("code_number", na_position="last")
        else:
            subset = subset.sort_values("Name")

        points = []
        for _, row in subset.iterrows():
            try:
                points.append((float(row["Easting"]), float(row["Northing"])))
            except (ValueError, TypeError):
                continue

        if len(points) < 2:
            return

        color = get_feature_config(self.config, base_code).get("color", 7)
        msp.add_lwpolyline(
            points,
            close=close,
            dxfattribs={"layer": layer, "color": color},
        )
        logger.info(
            "Auto-connected %d %s points on layer %s", len(points), base_code, layer
        )

    def _draw_elevation_callouts(self, df: pd.DataFrame, msp: Modelspace) -> None:
        """Draw a POINT + elevation TEXT on V-TOPO-SPOT for GR (grade shot) codes."""
        gr_rows = self._filter_by_code(df, "GR")
        feat_cfg = get_feature_config(self.config, "GR")
        if not feat_cfg.get("label_elevation", True):
            return

        layer = feat_cfg.get("layer", "V-TOPO-SPOT")
        color = feat_cfg.get("color", 4)

        for _, row in gr_rows.iterrows():
            try:
                x = float(row["Easting"])
                y = float(row["Northing"])
                z = float(row["Elevation"])
            except (ValueError, TypeError):
                continue

            # Spot elevation tick mark (small cross via POINT, already done in _write_points)
            # Add a clearly formatted elevation label below the point
            elev_label = f"{z:.2f}"
            msp.add_text(
                elev_label,
                dxfattribs={
                    "layer": layer,
                    "height": self.text_height * 0.8,
                    "insert": (x + _DEFAULT_TEXT_OFFSET, y - self.text_height, z),
                    "color": color,
                },
            )

    def _draw_contours(self, df: pd.DataFrame, msp: Modelspace) -> None:
        """Generate and draw contour lines from GR (grade shot) points."""
        from poolbridge.contouring import generate_contours

        contour_cfg = self.config.get("contours", {})
        if not contour_cfg.get("enabled", False):
            return

        gr = self._filter_by_code(df, "GR")
        try:
            cols = ["Easting", "Northing", "Elevation"]
            gr_coords = gr[cols].apply(pd.to_numeric, errors="coerce").dropna()
            x = gr_coords["Easting"].values
            y = gr_coords["Northing"].values
            z = gr_coords["Elevation"].values
        except Exception:
            return

        major_segs, minor_segs = generate_contours(
            x, y, z,
            major_interval=float(contour_cfg.get("major_interval", 1.0)),
            minor_interval=float(contour_cfg.get("minor_interval", 0.25)),
            grid_cells=int(contour_cfg.get("grid_cells", 150)),
        )

        for (x1, y1), (x2, y2) in major_segs:
            msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": "V-TOPO-MAJR"})
        for (x1, y1), (x2, y2) in minor_segs:
            msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": "V-TOPO-MINR"})
        logger.info(
            "Drew %d major + %d minor contour segments",
            len(major_segs), len(minor_segs),
        )


# ---------------------------------------------------------------------------
# PENZD CSV export
# ---------------------------------------------------------------------------

def export_penzd_csv(df: pd.DataFrame, output_path: str) -> None:
    """Export a PENZD (Point, Easting, Northing, Z, Description) CSV.

    This format can be re-imported into Emlid Flow or other survey software
    for stakeout operations.

    Args:
        df: Processed survey DataFrame.
        output_path: Destination .csv file path.
    """
    out = pd.DataFrame({
        "Point": df["Name"].astype(str),
        "Easting": pd.to_numeric(df["Easting"], errors="coerce").round(4),
        "Northing": pd.to_numeric(df["Northing"], errors="coerce").round(4),
        "Elevation": pd.to_numeric(df["Elevation"], errors="coerce").round(4),
        "Description": df.get("Description", pd.Series([""] * len(df))).fillna(""),
    })
    out.to_csv(output_path, index=False)
    logger.info("PENZD CSV written to %s (%d rows)", output_path, len(out))


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _parse_drip_radius_ft(description: str) -> Optional[float]:
    """Extract tree drip-line radius in feet from a Description string.

    Supports formats: D=12', D=12ft, D=3.66m, DIA=12, 12' dia.

    Args:
        description: The Description column value for a tree point.

    Returns:
        Radius in feet, or None if no diameter found.
    """
    if not description:
        return None

    for i, pattern in enumerate(_DIAMETER_PATTERNS):
        m = pattern.search(description)
        if m:
            val = float(m.group(1))
            if i == 2:  # meters pattern — convert to feet
                from poolbridge.localization import METERS_TO_US_SURVEY_FEET
                val = val * METERS_TO_US_SURVEY_FEET
            return val / 2.0  # diameter → radius

    return None
