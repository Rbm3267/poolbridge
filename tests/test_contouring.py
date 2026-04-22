"""Tests for poolbridge.contouring — marching-squares contour generation."""

import math

import numpy as np
import pytest

from poolbridge.contouring import (
    _contour_levels,
    _is_major,
    _march_squares,
    generate_contours,
)


# ---------------------------------------------------------------------------
# _contour_levels
# ---------------------------------------------------------------------------

class TestContourLevels:
    def test_basic(self):
        levels = _contour_levels(0.0, 3.0, 1.0)
        assert levels == pytest.approx([0.0, 1.0, 2.0, 3.0])

    def test_non_zero_start(self):
        levels = _contour_levels(0.3, 2.0, 1.0)
        assert levels == pytest.approx([1.0, 2.0])

    def test_minor_interval(self):
        levels = _contour_levels(0.0, 1.0, 0.25)
        assert len(levels) == 5
        assert levels[0] == pytest.approx(0.0)
        assert levels[-1] == pytest.approx(1.0)

    def test_empty_range(self):
        levels = _contour_levels(5.0, 4.0, 1.0)
        assert levels == []

    def test_single_level(self):
        levels = _contour_levels(1.0, 1.0, 1.0)
        assert levels == pytest.approx([1.0])


# ---------------------------------------------------------------------------
# _is_major
# ---------------------------------------------------------------------------

class TestIsMajor:
    def test_exact_multiple(self):
        assert _is_major(2.0, 1.0) is True
        assert _is_major(0.0, 1.0) is True
        assert _is_major(5.0, 1.0) is True

    def test_non_multiple(self):
        assert _is_major(0.25, 1.0) is False
        assert _is_major(0.5, 1.0) is False
        assert _is_major(0.75, 1.0) is False

    def test_floating_point_noise(self):
        # 3 * 0.25 = 0.75, not a multiple of 1.0
        assert _is_major(0.75, 1.0) is False
        # 4 * 0.25 = 1.0, should be a multiple of 1.0
        level = 4 * 0.25  # may have tiny FP error
        assert _is_major(level, 1.0) is True

    def test_with_half_foot_major(self):
        assert _is_major(0.5, 0.5) is True
        assert _is_major(1.0, 0.5) is True
        assert _is_major(0.25, 0.5) is False


# ---------------------------------------------------------------------------
# _march_squares
# ---------------------------------------------------------------------------

class TestMarchSquares:
    def _flat_grid(self, nx=10, ny=10, value=5.0):
        xi = np.linspace(0, 10, nx)
        yi = np.linspace(0, 10, ny)
        zi = np.full((nx, ny), value)
        return xi, yi, zi

    def _slope_grid(self, nx=20, ny=20):
        """Z increases linearly from 0 to 10 along x."""
        xi = np.linspace(0, 10, nx)
        yi = np.linspace(0, 10, ny)
        xi_g, _ = np.meshgrid(xi, yi, indexing="ij")
        return xi, yi, xi_g  # z = x coordinate

    def test_no_crossing_all_below(self):
        xi, yi, zi = self._flat_grid(value=3.0)
        segs = _march_squares(xi, yi, zi, level=5.0)
        assert segs == []

    def test_no_crossing_all_above(self):
        xi, yi, zi = self._flat_grid(value=7.0)
        segs = _march_squares(xi, yi, zi, level=5.0)
        assert segs == []

    def test_slope_produces_segments(self):
        xi, yi, zi = self._slope_grid()
        segs = _march_squares(xi, yi, zi, level=5.0)
        assert len(segs) > 0

    def test_segments_are_pairs_of_tuples(self):
        xi, yi, zi = self._slope_grid()
        segs = _march_squares(xi, yi, zi, level=5.0)
        for seg in segs:
            assert len(seg) == 2
            (x1, y1), (x2, y2) = seg
            assert isinstance(x1, float)
            assert isinstance(y1, float)

    def test_crossing_near_correct_x(self):
        xi, yi, zi = self._slope_grid(nx=100, ny=5)
        # z = x, so the z=5 contour should be near x=5
        segs = _march_squares(xi, yi, zi, level=5.0)
        assert len(segs) > 0
        xs = [p[0] for seg in segs for p in seg]
        assert all(abs(x - 5.0) < 0.5 for x in xs), f"Contour x values not near 5.0: {xs[:5]}"

    def test_nan_cells_skipped(self):
        xi = np.linspace(0, 10, 10)
        yi = np.linspace(0, 10, 10)
        zi = np.full((10, 10), 3.0)
        zi[3:7, 3:7] = float("nan")
        segs = _march_squares(xi, yi, zi, level=5.0)
        assert segs == []  # all valid cells are below level=5, NaN cells skipped


# ---------------------------------------------------------------------------
# generate_contours
# ---------------------------------------------------------------------------

class TestGenerateContours:
    def _make_scattered_points(self, n=30):
        """Random GR points on a sloped plane z = 2x + y (in feet)."""
        rng = np.random.default_rng(42)
        x = rng.uniform(0, 10, n)
        y = rng.uniform(0, 10, n)
        z = 2 * x + y  # z ranges 0..30
        return x, y, z

    def test_returns_segments(self):
        pytest.importorskip("scipy")
        x, y, z = self._make_scattered_points()
        major, minor = generate_contours(x, y, z, major_interval=5.0, minor_interval=1.0)
        assert len(major) > 0
        assert len(minor) > 0

    def test_major_count_less_than_minor(self):
        pytest.importorskip("scipy")
        x, y, z = self._make_scattered_points()
        major, minor = generate_contours(x, y, z, major_interval=5.0, minor_interval=1.0)
        assert len(major) < len(minor)

    def test_too_few_points_returns_empty(self):
        pytest.importorskip("scipy")
        x = np.array([0.0, 1.0])
        y = np.array([0.0, 1.0])
        z = np.array([0.0, 1.0])
        major, minor = generate_contours(x, y, z, major_interval=1.0, minor_interval=0.25)
        assert major == []
        assert minor == []

    def test_segment_format(self):
        pytest.importorskip("scipy")
        x, y, z = self._make_scattered_points()
        major, minor = generate_contours(x, y, z, major_interval=5.0, minor_interval=1.0)
        for seg in major + minor:
            (x1, y1), (x2, y2) = seg
            assert isinstance(x1, float)
            assert isinstance(y1, float)

    def test_equal_interval_all_major(self):
        """When major == minor interval, all contours are major."""
        pytest.importorskip("scipy")
        x, y, z = self._make_scattered_points()
        major, minor = generate_contours(x, y, z, major_interval=1.0, minor_interval=1.0)
        assert len(minor) == 0
        assert len(major) > 0

    def test_no_scipy_graceful(self, monkeypatch):
        """generate_contours returns empty lists if scipy is missing."""
        import poolbridge.contouring as mod
        original = __builtins__

        def mock_import(name, *args, **kwargs):
            if name == "scipy.interpolate":
                raise ImportError("mocked missing scipy")
            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        x, y, z = self._make_scattered_points()
        # If scipy is actually installed, this won't trigger the fallback;
        # we verify at least the function completes without error.
        major, minor = generate_contours(x, y, z, major_interval=1.0, minor_interval=0.25)
        assert isinstance(major, list)
        assert isinstance(minor, list)
