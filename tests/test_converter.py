"""Integration and unit tests for the conversion pipeline."""

import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from poolbridge.converter import PoolBridgeConverter, _penzd_path
from poolbridge.dxf_writer import _parse_drip_radius_ft, export_penzd_csv
from poolbridge.validation import (
    ValidationError,
    validate_control_points,
    validate_dataframe,
)


SAMPLE_CSV = Path(__file__).parent.parent / "examples" / "sample_emlid_export.csv"
SAMPLE_CONFIG = Path(__file__).parent.parent / "examples" / "sample_config.yaml"


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

class TestCSVLoading:
    def test_loads_sample_csv(self):
        converter = PoolBridgeConverter()
        df = converter._load_csv(str(SAMPLE_CSV))
        assert len(df) > 0
        for col in ("Name", "Code", "Easting", "Northing", "Elevation"):
            assert col in df.columns

    def test_numeric_columns_are_float(self):
        converter = PoolBridgeConverter()
        df = converter._load_csv(str(SAMPLE_CSV))
        assert df["Easting"].dtype in (float, "float64")
        assert df["Northing"].dtype in (float, "float64")
        assert df["Elevation"].dtype in (float, "float64")

    def test_raises_on_missing_file(self):
        converter = PoolBridgeConverter()
        with pytest.raises(FileNotFoundError):
            converter._load_csv("/no/such/file.csv")

    def test_utf8_bom_handled(self, tmp_path):
        csv_content = "Name,Code,Easting,Northing,Elevation\nPT1,GR,100.0,200.0,10.0\n"
        # Write with BOM
        p = tmp_path / "bom.csv"
        p.write_bytes(b"\xef\xbb\xbf" + csv_content.encode("utf-8"))
        converter = PoolBridgeConverter()
        df = converter._load_csv(str(p))
        assert list(df.columns[:5]) == ["Name", "Code", "Easting", "Northing", "Elevation"]


# ---------------------------------------------------------------------------
# Feature code parsing
# ---------------------------------------------------------------------------

class TestFeatureCodeParsing:
    def _make_df(self, codes):
        return pd.DataFrame({
            "Name": [f"PT{i}" for i in range(len(codes))],
            "Code": codes,
            "Easting": [0.0] * len(codes),
            "Northing": [0.0] * len(codes),
            "Elevation": [0.0] * len(codes),
        })

    def test_simple_code_extracted(self):
        converter = PoolBridgeConverter()
        df = self._make_df(["HC"])
        out = converter._parse_feature_codes(df)
        assert out.iloc[0]["base_code"] == "HC"
        assert out.iloc[0]["code_number"] is None

    def test_numbered_code_split(self):
        converter = PoolBridgeConverter()
        df = self._make_df(["PC-1", "PC-2", "PC-3"])
        out = converter._parse_feature_codes(df)
        assert list(out["base_code"]) == ["PC", "PC", "PC"]
        assert list(out["code_number"]) == [1, 2, 3]

    def test_codes_uppercased(self):
        converter = PoolBridgeConverter()
        df = self._make_df(["hc", "gr1"])
        out = converter._parse_feature_codes(df)
        assert out.iloc[0]["base_code"] == "HC"
        assert out.iloc[1]["base_code"] == "GR"

    def test_sample_csv_codes_parsed(self):
        converter = PoolBridgeConverter()
        df = converter._load_csv(str(SAMPLE_CSV))
        out = converter._parse_feature_codes(df)
        codes = set(out["base_code"].unique())
        assert "HC" in codes
        assert "PC" in codes
        assert "GR" in codes
        assert "TR" in codes


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_df_passes(self):
        df = pd.DataFrame({
            "Name": ["PT1"],
            "Code": ["GR"],
            "Easting": [100.0],
            "Northing": [200.0],
            "Elevation": [10.0],
        })
        warns = validate_dataframe(df)
        assert isinstance(warns, list)

    def test_missing_column_raises(self):
        df = pd.DataFrame({"Name": ["PT1"], "Code": ["GR"], "Easting": [0.0]})
        with pytest.raises(ValidationError, match="missing required column"):
            validate_dataframe(df)

    def test_duplicate_names_warn(self):
        df = pd.DataFrame({
            "Name": ["PT1", "PT1", "PT2"],
            "Code": ["GR", "GR", "HC"],
            "Easting": [0.0, 0.0, 1.0],
            "Northing": [0.0, 0.0, 1.0],
            "Elevation": [0.0, 0.0, 0.0],
        })
        warns = validate_dataframe(df)
        assert any("Duplicate" in w for w in warns)

    def test_negative_elevation_warns(self):
        df = pd.DataFrame({
            "Name": ["PT1"],
            "Code": ["GR"],
            "Easting": [100.0],
            "Northing": [200.0],
            "Elevation": [-25.0],
        })
        warns = validate_dataframe(df)
        assert any("ellipsoidal" in w.lower() or "negative" in w.lower() for w in warns)

    def test_control_points_missing_raises(self):
        df = pd.DataFrame({
            "Name": ["PT1"],
            "Code": ["GR"],
            "Easting": [100.0],
            "Northing": [200.0],
            "Elevation": [10.0],
        })
        cps = [
            {"name": "CP-1", "known_easting": 0.0, "known_northing": 0.0},
            {"name": "CP-2", "known_easting": 10.0, "known_northing": 0.0},
        ]
        with pytest.raises(ValidationError, match="not found"):
            validate_control_points(df, cps)

    def test_fewer_than_two_control_points_raises(self):
        df = pd.DataFrame({
            "Name": ["CP-1"], "Code": ["CP"],
            "Easting": [0.0], "Northing": [0.0], "Elevation": [0.0],
        })
        with pytest.raises(ValidationError, match="at least 2"):
            validate_control_points(df, [{"name": "CP-1", "known_easting": 0.0, "known_northing": 0.0}])


# ---------------------------------------------------------------------------
# DXF writer helpers
# ---------------------------------------------------------------------------

class TestParseDripRadius:
    def test_feet_format(self):
        assert abs(_parse_drip_radius_ft("D=14'") - 7.0) < 1e-6

    def test_ft_format(self):
        assert abs(_parse_drip_radius_ft("D=12ft") - 6.0) < 1e-6

    def test_meters_format(self):
        result = _parse_drip_radius_ft("D=4.0m")
        expected = (4.0 * 3937 / 1200) / 2
        assert abs(result - expected) < 1e-4

    def test_dia_colon_format(self):
        assert abs(_parse_drip_radius_ft("DIA:10") - 5.0) < 1e-6

    def test_verbose_dia_format(self):
        assert abs(_parse_drip_radius_ft("14' dia") - 7.0) < 1e-6

    def test_empty_string_returns_none(self):
        assert _parse_drip_radius_ft("") is None

    def test_no_diameter_returns_none(self):
        assert _parse_drip_radius_ft("Live oak, healthy") is None

    def test_description_with_extra_text(self):
        result = _parse_drip_radius_ft("Pecan D=8' drip line")
        assert abs(result - 4.0) < 1e-6


# ---------------------------------------------------------------------------
# PENZD CSV export
# ---------------------------------------------------------------------------

class TestExportPENZD:
    def test_output_has_required_columns(self, tmp_path):
        df = pd.DataFrame({
            "Name": ["PT1", "PT2"],
            "Easting": [10.0, 20.0],
            "Northing": [30.0, 40.0],
            "Elevation": [5.0, 6.0],
            "Description": ["desc1", "desc2"],
        })
        out = tmp_path / "out.csv"
        export_penzd_csv(df, str(out))
        result = pd.read_csv(str(out))
        for col in ("Point", "Easting", "Northing", "Elevation", "Description"):
            assert col in result.columns

    def test_row_count_matches(self, tmp_path):
        df = pd.DataFrame({
            "Name": ["PT1", "PT2", "PT3"],
            "Easting": [1.0, 2.0, 3.0],
            "Northing": [1.0, 2.0, 3.0],
            "Elevation": [0.0, 0.0, 0.0],
        })
        out = tmp_path / "penzd.csv"
        export_penzd_csv(df, str(out))
        result = pd.read_csv(str(out))
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Full pipeline integration test
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_sample_conversion_produces_dxf(self, tmp_path):
        output = tmp_path / "output.dxf"
        converter = PoolBridgeConverter(str(SAMPLE_CONFIG))
        result = converter.convert(
            input_csv=str(SAMPLE_CSV),
            output_dxf=str(output),
        )
        assert output.exists()
        assert result.point_count > 0

    def test_penzd_csv_created(self, tmp_path):
        output = tmp_path / "output.dxf"
        converter = PoolBridgeConverter(str(SAMPLE_CONFIG))
        result = converter.convert(
            input_csv=str(SAMPLE_CSV),
            output_dxf=str(output),
        )
        assert result.penzd_path is not None
        assert Path(result.penzd_path).exists()

    def test_localization_report_present(self, tmp_path):
        output = tmp_path / "output.dxf"
        converter = PoolBridgeConverter(str(SAMPLE_CONFIG))
        result = converter.convert(
            input_csv=str(SAMPLE_CSV),
            output_dxf=str(output),
        )
        assert result.localization_report is not None
        assert "RMS" in result.localization_report

    def test_skip_localization_still_produces_dxf(self, tmp_path):
        output = tmp_path / "output.dxf"
        converter = PoolBridgeConverter(str(SAMPLE_CONFIG))
        result = converter.convert(
            input_csv=str(SAMPLE_CSV),
            output_dxf=str(output),
            skip_localization=True,
        )
        assert output.exists()
        assert result.localization_report is None

    def test_no_config_uses_defaults(self, tmp_path):
        output = tmp_path / "output.dxf"
        converter = PoolBridgeConverter()
        result = converter.convert(
            input_csv=str(SAMPLE_CSV),
            output_dxf=str(output),
            skip_localization=True,
        )
        assert output.exists()

    def test_dxf_contains_expected_layers(self, tmp_path):
        import ezdxf
        output = tmp_path / "output.dxf"
        converter = PoolBridgeConverter(str(SAMPLE_CONFIG))
        converter.convert(
            input_csv=str(SAMPLE_CSV),
            output_dxf=str(output),
        )
        doc = ezdxf.readfile(str(output))
        layer_names = {layer.dxf.name for layer in doc.layers}
        assert "V-PROP" in layer_names
        assert "V-BLDG" in layer_names
        assert "V-TOPO-SPOT" in layer_names
        assert "V-PLNT-TREE" in layer_names

    def test_dxf_insunits_decimal_feet(self, tmp_path):
        import ezdxf
        output = tmp_path / "output.dxf"
        converter = PoolBridgeConverter(str(SAMPLE_CONFIG))
        converter.convert(
            input_csv=str(SAMPLE_CSV),
            output_dxf=str(output),
        )
        doc = ezdxf.readfile(str(output))
        assert doc.header["$INSUNITS"] == 2

    def test_dxf_pdmode_set(self, tmp_path):
        import ezdxf
        output = tmp_path / "output.dxf"
        converter = PoolBridgeConverter(str(SAMPLE_CONFIG))
        converter.convert(
            input_csv=str(SAMPLE_CSV),
            output_dxf=str(output),
        )
        doc = ezdxf.readfile(str(output))
        assert doc.header["$PDMODE"] == 35


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_penzd_path_derivation():
    assert _penzd_path("output.dxf") == "output_penzd.csv"
    assert _penzd_path("/path/to/site.dxf") == "/path/to/site_penzd.csv"
