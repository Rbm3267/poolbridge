"""Main 6-stage conversion pipeline: CSV → feature parse → reproject → localize → units → DXF."""

import logging
import os
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from poolbridge.config import load_config, get_feature_config
from poolbridge.dxf_writer import DXFWriter, export_penzd_csv
from poolbridge.readers import read_file
from poolbridge.localization import (
    METERS_TO_US_SURVEY_FEET,
    apply_transform_dataframe,
    extract_control_coords,
    format_localization_report,
    helmert_transform,
    meters_to_feet,
    reproject_dataframe,
    two_point_transform,
)
from poolbridge.validation import (
    ValidationError,
    validate_control_points,
    validate_dataframe,
    validate_transform_result,
)

logger = logging.getLogger(__name__)

# Emlid CSV may carry a UTF-8 BOM; pandas will strip it when encoding='utf-8-sig'
_CSV_ENCODING = "utf-8-sig"

# Pattern to split a code like "PC-1" into base="PC" and number=1
_CODE_SPLIT_RE = re.compile(r"^([A-Za-z]+)[^0-9]*(\d+)?$")


class ConversionResult:
    """Holds the outputs and metadata from a conversion run.

    Attributes:
        dxf_path: Path to the generated DXF file.
        penzd_path: Path to the generated PENZD CSV, or None.
        warnings: List of non-fatal warning messages.
        localization_report: Human-readable residual report, or None.
        point_count: Number of survey points written to DXF.
    """

    def __init__(
        self,
        dxf_path: str,
        penzd_path: Optional[str],
        warnings: List[str],
        localization_report: Optional[str],
        point_count: int,
    ) -> None:
        self.dxf_path = dxf_path
        self.penzd_path = penzd_path
        self.warnings = warnings
        self.localization_report = localization_report
        self.point_count = point_count

    def __str__(self) -> str:
        lines = [
            f"Conversion complete: {self.point_count} points",
            f"  DXF   : {self.dxf_path}",
        ]
        if self.penzd_path:
            lines.append(f"  PENZD : {self.penzd_path}")
        if self.localization_report:
            lines.append(self.localization_report)
        if self.warnings:
            lines.append("\nWarnings:")
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        return "\n".join(lines)


class PoolBridgeConverter:
    """Orchestrates the 6-stage Emlid CSV → Pool Studio DXF conversion pipeline.

    Args:
        config_path: Optional path to a YAML or JSON config file. If None,
            built-in defaults are used.
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.config = load_config(config_path)
        logger.debug("PoolBridgeConverter initialized (config_path=%s)", config_path)

    def convert(
        self,
        input_csv: str,
        output_dxf: str,
        *,
        target_crs: Optional[str] = None,
        z_offset: Optional[float] = None,
        skip_localization: bool = False,
    ) -> ConversionResult:
        """Run the full conversion pipeline.

        Args:
            input_csv: Path to the Emlid Flow CSV export.
            output_dxf: Destination DXF file path.
            target_crs: Override the target CRS (e.g. 'EPSG:32614'). If provided,
                takes precedence over config.
            z_offset: Override the Z datum offset in meters. Subtracted from
                Elevation before unit conversion.
            skip_localization: If True, skip the localization step even if control
                points are defined in config.

        Returns:
            ConversionResult with paths, warnings, and localization report.
        """
        warn_messages: List[str] = []

        # --- Stage 1: Load file (CSV, PENZD, KML, Shapefile, or DXF) ----------
        logger.info("Stage 1: Loading %s", input_csv)
        df = self._load_file(input_csv)

        # --- Validate ---------------------------------------------------------
        validation_warns = validate_dataframe(df)
        warn_messages.extend(validation_warns)
        for w in validation_warns:
            logger.warning(w)

        # --- Stage 2: Parse feature codes ------------------------------------
        logger.info("Stage 2: Parsing feature codes")
        df = self._parse_feature_codes(df)

        # --- Stage 3: Reproject ----------------------------------------------
        logger.info("Stage 3: Reprojecting coordinates")
        df, reproject_warn = self._reproject(df, target_crs)
        if reproject_warn:
            warn_messages.append(reproject_warn)
            logger.warning(reproject_warn)

        # --- Stage 4: Localize -----------------------------------------------
        localization_report: Optional[str] = None
        if not skip_localization:
            logger.info("Stage 4: Localizing coordinates")
            df, localization_report, loc_warns = self._localize(df)
            warn_messages.extend(loc_warns)
        else:
            logger.info("Stage 4: Localization skipped")

        # --- Stage 5: Unit conversion ----------------------------------------
        logger.info("Stage 5: Converting units (m → US survey ft)")
        df = self._convert_units(df, z_offset)

        # --- Stage 6: Write DXF -----------------------------------------------
        logger.info("Stage 6: Writing DXF to %s", output_dxf)
        writer = DXFWriter(self.config)
        writer.write(df, output_dxf)

        # --- Optional: Export PENZD CSV ---------------------------------------
        penzd_path: Optional[str] = None
        if self.config.get("output", {}).get("export_penzd_csv", True):
            penzd_path = _penzd_path(output_dxf)
            export_penzd_csv(df, penzd_path)

        return ConversionResult(
            dxf_path=output_dxf,
            penzd_path=penzd_path,
            warnings=warn_messages,
            localization_report=localization_report,
            point_count=len(df),
        )

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> pd.DataFrame:
        """Load any supported Emlid export format via the readers module."""
        return read_file(path)

    def _load_csv(self, csv_path: str) -> pd.DataFrame:
        """Backwards-compatible alias for _load_file."""
        return self._load_file(csv_path)

    def _parse_feature_codes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Split Code column into base_code and code_number for smart features."""
        df = df.copy()
        base_codes = []
        code_numbers = []
        for raw_code in df["Code"].astype(str):
            raw_code = raw_code.strip()
            m = _CODE_SPLIT_RE.match(raw_code)
            if m:
                base_codes.append(m.group(1).upper())
                num = m.group(2)
                code_numbers.append(int(num) if num else None)
            else:
                base_codes.append(raw_code.upper())
                code_numbers.append(None)

        df["base_code"] = base_codes
        df["code_number"] = pd.array(code_numbers, dtype="object")
        return df

    def _reproject(
        self,
        df: pd.DataFrame,
        target_crs_override: Optional[str],
    ) -> Tuple[pd.DataFrame, Optional[str]]:
        """Reproject if source/target CRS are configured and differ.

        Respects the Emlid 'Origin' column: points tagged 'Local' already
        carry projected E/N and are excluded from reprojection so they are
        not double-transformed.
        """
        crs_cfg = self.config.get("coordinate_system", {})
        source_crs = crs_cfg.get("source_crs", "EPSG:4326")
        target_crs = target_crs_override or crs_cfg.get("target_crs")

        # Check Origin column — Local points must skip reprojection
        warn: Optional[str] = None
        if "Origin" in df.columns:
            origins = df["Origin"].astype(str).str.strip().str.lower()
            all_local = (origins == "local").all()
            any_local = (origins == "local").any()
            any_global = origins.isin(["global", "nan", ""]).any()

            if all_local:
                logger.info("All points have Local origin; skipping reprojection.")
                return df, None

            if any_local and any_global:
                warn = (
                    "Mixed Local/Global origins detected. Only Global points will be "
                    "reprojected; Local points use their Easting/Northing as-is."
                )
                logger.warning(warn)
                if not target_crs:
                    return df, warn
                global_mask = ~(origins == "local")
                df_global = df[global_mask].copy()
                df_local = df[~global_mask].copy()
                try:
                    df_global = reproject_dataframe(df_global, source_crs, target_crs)
                except Exception as exc:
                    raise RuntimeError(
                        f"Reprojection from {source_crs} to {target_crs} failed: {exc}"
                    ) from exc
                df = pd.concat([df_local, df_global]).sort_index()
                return df, warn

        if not target_crs:
            no_crs_warn = (
                "No target CRS configured — using Easting/Northing columns as-is. "
                "Set coordinate_system.target_crs in your config if reprojection is needed."
            )
            return df, no_crs_warn

        if source_crs.upper() == (target_crs or "").upper():
            logger.info("Source and target CRS match (%s); skipping reprojection", source_crs)
            return df, warn

        try:
            df = reproject_dataframe(df, source_crs, target_crs)
        except Exception as exc:
            raise RuntimeError(
                f"Reprojection from {source_crs} to {target_crs} failed: {exc}"
            ) from exc

        return df, warn

    def _localize(
        self,
        df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, Optional[str], List[str]]:
        """Apply rigid-body localization if control points are configured."""
        warn_messages: List[str] = []
        loc_cfg = self.config.get("localization", {})
        control_points = loc_cfg.get("control_points", [])

        if not control_points:
            logger.info("No control points configured; skipping localization")
            return df, None, []

        # Validate control points exist in data
        try:
            cp_warns = validate_control_points(df, control_points)
        except ValidationError as exc:
            raise RuntimeError(str(exc)) from exc
        warn_messages.extend(cp_warns)

        src_pts, tgt_pts = extract_control_coords(df, control_points)

        method = loc_cfg.get("method", "two_point")
        if method == "helmert" or len(src_pts) >= 3:
            transform = helmert_transform(src_pts, tgt_pts)
        else:
            transform = two_point_transform(src_pts, tgt_pts)

        transform_warns = validate_transform_result(transform)
        warn_messages.extend(transform_warns)

        df = apply_transform_dataframe(df, transform)

        report = format_localization_report(
            control_points, src_pts, tgt_pts, transform
        )
        return df, report, warn_messages

    def _convert_units(
        self,
        df: pd.DataFrame,
        z_offset_override: Optional[float],
    ) -> pd.DataFrame:
        """Apply Z-datum offset then convert m → US survey ft."""
        z_cfg = self.config.get("z_datum", {})
        z_offset = z_offset_override

        if z_offset is None:
            z_offset = float(z_cfg.get("offset", 0.0))

        if z_cfg.get("method") == "point":
            ref_name = z_cfg.get("reference_point")
            if ref_name:
                mask = df["Name"].astype(str).str.strip() == str(ref_name).strip()
                ref_rows = df[mask]
                if not ref_rows.empty:
                    z_offset = -float(ref_rows.iloc[0]["Elevation"])
                    logger.info(
                        "Z datum: using elevation of '%s' (%.4f m) as zero baseline",
                        ref_name,
                        -z_offset,
                    )

        if z_offset != 0.0:
            df = df.copy()
            df["Elevation"] = pd.to_numeric(df["Elevation"], errors="coerce") + z_offset
            logger.info("Applied Z datum offset: %.4f m", z_offset)

        if self.config.get("units", {}).get("convert_to_feet", True):
            df = meters_to_feet(df)

        return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _penzd_path(dxf_path: str) -> str:
    """Derive a PENZD CSV path from a DXF path."""
    base = os.path.splitext(dxf_path)[0]
    return base + "_penzd.csv"
