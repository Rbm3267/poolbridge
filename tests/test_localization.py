"""Tests for coordinate reprojection and localization transforms."""

import math

import numpy as np
import pandas as pd
import pytest

from poolbridge.localization import (
    METERS_TO_US_SURVEY_FEET,
    apply_transform,
    apply_transform_dataframe,
    extract_control_coords,
    format_localization_report,
    helmert_transform,
    meters_to_feet,
    two_point_transform,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOL = 1e-6  # tolerance for floating-point comparisons


# ---------------------------------------------------------------------------
# two_point_transform
# ---------------------------------------------------------------------------

class TestTwoPointTransform:
    def test_pure_translation(self):
        src = [(0.0, 0.0), (10.0, 0.0)]
        tgt = [(5.0, 3.0), (15.0, 3.0)]
        t = two_point_transform(src, tgt)
        assert abs(t["tx"] - 5.0) < _TOL
        assert abs(t["ty"] - 3.0) < _TOL
        assert abs(t["theta"]) < _TOL
        assert abs(t["scale"] - 1.0) < _TOL
        assert t["rms"] < _TOL

    def test_pure_rotation_90deg(self):
        # Rotate 90° CCW: (1,0) → (0,1), (0,1) → (-1,0)
        src = [(1.0, 0.0), (0.0, 1.0)]
        tgt = [(0.0, 1.0), (-1.0, 0.0)]
        t = two_point_transform(src, tgt)
        # atan2 may return -270° for this geometry; normalise to (-180, 180]
        angle_deg = math.degrees(t["theta"]) % 360
        if angle_deg > 180:
            angle_deg -= 360
        assert abs(angle_deg - 90.0) < 1e-4
        assert abs(t["scale"] - 1.0) < _TOL
        assert t["rms"] < _TOL

    def test_residuals_zero_for_two_points(self):
        src = [(621000.0, 3348120.0), (621030.0, 3348120.0)]
        tgt = [(0.0, 0.0), (30.0, 0.0)]
        t = two_point_transform(src, tgt)
        assert t["rms"] < _TOL
        for r in t["residuals"]:
            assert r < _TOL

    def test_apply_transform_on_control_points(self):
        src = [(621000.0, 3348120.0), (621030.0, 3348120.0)]
        tgt = [(0.0, 0.0), (30.0, 0.0)]
        t = two_point_transform(src, tgt)
        x1, y1 = apply_transform(621000.0, 3348120.0, t)
        assert abs(x1) < _TOL
        assert abs(y1) < _TOL
        x2, y2 = apply_transform(621030.0, 3348120.0, t)
        assert abs(x2 - 30.0) < _TOL
        assert abs(y2) < _TOL

    def test_transform_third_point(self):
        src = [(0.0, 0.0), (10.0, 0.0)]
        tgt = [(100.0, 200.0), (110.0, 200.0)]
        t = two_point_transform(src, tgt)
        x, y = apply_transform(5.0, 0.0, t)
        assert abs(x - 105.0) < _TOL
        assert abs(y - 200.0) < _TOL

    def test_coincident_points_raises(self):
        with pytest.raises(ValueError, match="coincident"):
            two_point_transform([(0.0, 0.0), (0.0, 0.0)], [(0.0, 0.0), (1.0, 0.0)])

    def test_wrong_count_raises(self):
        with pytest.raises(ValueError):
            two_point_transform([(0, 0)], [(0, 0)])

    def test_rotation_and_translation(self):
        # 45° rotation + translation
        theta = math.radians(45)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        src = [(0.0, 0.0), (10.0, 0.0)]
        tgt = [
            (5.0, 5.0),
            (5.0 + cos_t * 10, 5.0 + sin_t * 10),
        ]
        t = two_point_transform(src, tgt)
        assert abs(math.degrees(t["theta"]) - 45.0) < 1e-4
        assert t["rms"] < _TOL


# ---------------------------------------------------------------------------
# helmert_transform
# ---------------------------------------------------------------------------

class TestHelmertTransform:
    def test_two_points_matches_two_point_transform(self):
        # Use small coordinates to avoid conditioning issues with lstsq
        src = [(10.0, 20.0), (40.0, 20.0)]
        tgt = [(0.0, 0.0), (30.0, 0.0)]
        h = helmert_transform(src, tgt)
        tp = two_point_transform(src, tgt)
        assert abs(h["theta"] - tp["theta"]) < 1e-5
        assert abs(h["scale"] - tp["scale"]) < 1e-5
        assert abs(h["tx"] - tp["tx"]) < 1e-4
        assert abs(h["ty"] - tp["ty"]) < 1e-4

    def test_four_points_produces_residuals(self):
        # Exact transform — residuals should be near 0
        src = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        tgt = [(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]
        h = helmert_transform(src, tgt)
        assert h["rms"] < _TOL
        assert len(h["residuals"]) == 4

    def test_noisy_points_increases_rms(self):
        # Add a 0.1m blunder to one point
        src = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (5.0, 5.0)]
        tgt = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (5.1, 5.1)]
        h = helmert_transform(src, tgt)
        assert h["rms"] > 0.0

    def test_returns_residual_vectors(self):
        src = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        tgt = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        h = helmert_transform(src, tgt)
        assert "residual_vectors" in h
        assert len(h["residual_vectors"]) == 3

    def test_insufficient_points_raises(self):
        with pytest.raises(ValueError):
            helmert_transform([(0, 0)], [(1, 1)])


# ---------------------------------------------------------------------------
# apply_transform_dataframe
# ---------------------------------------------------------------------------

class TestApplyTransformDataframe:
    def _make_df(self):
        return pd.DataFrame({
            "Name": ["A", "B"],
            "Easting": [621000.0, 621010.0],
            "Northing": [3348120.0, 3348120.0],
            "Elevation": [10.0, 10.0],
        })

    def test_translation_applied_to_all_rows(self):
        df = self._make_df()
        t = {"a": 1.0, "b": 0.0, "tx": -621000.0, "ty": -3348120.0}
        out = apply_transform_dataframe(df, t)
        assert abs(float(out.iloc[0]["Easting"])) < _TOL
        assert abs(float(out.iloc[0]["Northing"])) < _TOL
        assert abs(float(out.iloc[1]["Easting"]) - 10.0) < _TOL

    def test_original_df_not_mutated(self):
        df = self._make_df()
        t = {"a": 1.0, "b": 0.0, "tx": 100.0, "ty": 0.0}
        apply_transform_dataframe(df, t)
        assert float(df.iloc[0]["Easting"]) == 621000.0


# ---------------------------------------------------------------------------
# meters_to_feet
# ---------------------------------------------------------------------------

class TestMetersToFeet:
    def test_conversion_factor(self):
        df = pd.DataFrame({"Easting": [1.0], "Northing": [1.0], "Elevation": [1.0]})
        out = meters_to_feet(df)
        expected = 3937.0 / 1200.0
        assert abs(float(out.iloc[0]["Easting"]) - expected) < 1e-8

    def test_zero_remains_zero(self):
        df = pd.DataFrame({"Easting": [0.0], "Northing": [0.0], "Elevation": [0.0]})
        out = meters_to_feet(df)
        assert float(out.iloc[0]["Easting"]) == 0.0

    def test_only_numeric_columns_converted(self):
        df = pd.DataFrame({
            "Easting": [1.0],
            "Northing": [1.0],
            "Elevation": [1.0],
            "Name": ["PT1"],
        })
        out = meters_to_feet(df)
        assert "Name" in out.columns
        assert list(out["Name"]) == ["PT1"]

    def test_constant_factor(self):
        assert abs(METERS_TO_US_SURVEY_FEET - 3937 / 1200) < 1e-12


# ---------------------------------------------------------------------------
# extract_control_coords
# ---------------------------------------------------------------------------

class TestExtractControlCoords:
    def _make_df(self):
        return pd.DataFrame({
            "Name": ["CP-1", "CP-2", "CP-3"],
            "Easting": [621000.0, 621030.0, 621015.0],
            "Northing": [3348120.0, 3348120.0, 3348145.0],
            "Elevation": [180.0, 180.0, 180.0],
        })

    def test_extracts_src_and_tgt(self):
        df = self._make_df()
        cps = [
            {"name": "CP-1", "known_easting": 0.0, "known_northing": 0.0},
            {"name": "CP-2", "known_easting": 30.0, "known_northing": 0.0},
        ]
        src, tgt = extract_control_coords(df, cps)
        assert src[0] == (621000.0, 3348120.0)
        assert tgt[0] == (0.0, 0.0)
        assert src[1] == (621030.0, 3348120.0)
        assert tgt[1] == (30.0, 0.0)


# ---------------------------------------------------------------------------
# format_localization_report
# ---------------------------------------------------------------------------

class TestFormatLocalizationReport:
    def test_report_contains_rms(self):
        src = [(0.0, 0.0), (10.0, 0.0)]
        tgt = [(0.0, 0.0), (10.0, 0.0)]
        t = two_point_transform(src, tgt)
        cps = [
            {"name": "CP-1", "known_easting": 0.0, "known_northing": 0.0},
            {"name": "CP-2", "known_easting": 10.0, "known_northing": 0.0},
        ]
        report = format_localization_report(cps, src, tgt, t)
        assert "RMS" in report
        assert "CP-1" in report
        assert "CP-2" in report
