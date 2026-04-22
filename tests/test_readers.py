"""Tests for poolbridge.readers — multi-format Emlid export reader."""

import os
import tempfile
import textwrap
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from poolbridge.readers import (
    _auto_csv,
    _code_from_name,
    _ensure_standard_columns,
    _nearest_text,
    read_emlid_csv,
    read_emlid_dxf,
    read_file,
    read_kml,
    read_penzd_csv,
    read_shapefile,
    read_shapefile_zip,
    STANDARD_COLUMNS,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _write_tmp(content: str, suffix: str) -> str:
    """Write content to a named temp file; caller must delete it."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


EMLID_CSV_CONTENT = textwrap.dedent("""\
    Name,Code,Easting,Northing,Elevation,Description,Longitude,Latitude,Origin
    CP-1,CP,621050.0,3348120.0,201.0,Control 1,-97.12345,30.25678,Global
    HC-1,HC,621080.0,3348150.0,202.5,House corner,-97.12300,30.25700,Global
    GR-1,GR,621090.0,3348160.0,200.0,Grade shot,-97.12290,30.25710,Global
""")

PENZD_CSV_CONTENT = textwrap.dedent("""\
    Point,Easting,Northing,Elevation,Description
    HC-1,100.0,200.0,50.0,House corner
    PC-1,110.0,210.0,51.0,Property corner
""")

KML_CONTENT = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <name>HC-1</name>
          <description>House corner</description>
          <Point><coordinates>-97.12300,30.25700,202.5</coordinates></Point>
        </Placemark>
        <Placemark>
          <name>GR-1</name>
          <description>Grade shot</description>
          <Point><coordinates>-97.12290,30.25710,200.0</coordinates></Point>
        </Placemark>
        <Folder>
          <Placemark>
            <name>Line1</name>
            <LineString><coordinates>0,0 1,1</coordinates></LineString>
          </Placemark>
        </Folder>
      </Document>
    </kml>
""")


# ---------------------------------------------------------------------------
# _code_from_name
# ---------------------------------------------------------------------------

class TestCodeFromName:
    def test_simple_code(self):
        assert _code_from_name("HC-1") == "HC"

    def test_code_no_number(self):
        assert _code_from_name("GR") == "GR"

    def test_empty(self):
        assert _code_from_name("") == ""

    def test_numeric_only(self):
        # No leading letters — returns empty
        assert _code_from_name("123") == ""

    def test_long_code(self):
        assert _code_from_name("ABCDEF-5") == "ABCDEF"


# ---------------------------------------------------------------------------
# _nearest_text
# ---------------------------------------------------------------------------

class TestNearestText:
    def _texts(self):
        return [
            {"x": 0.0, "y": 0.0, "text": "A"},
            {"x": 10.0, "y": 0.0, "text": "B"},
        ]

    def test_within_threshold(self):
        assert _nearest_text(0.1, 0.0, self._texts(), threshold=0.5) == "A"

    def test_outside_threshold(self):
        assert _nearest_text(1.0, 0.0, self._texts(), threshold=0.5) is None

    def test_picks_nearest(self):
        assert _nearest_text(9.8, 0.0, self._texts(), threshold=0.5) == "B"

    def test_empty_list(self):
        assert _nearest_text(0.0, 0.0, [], threshold=0.5) is None


# ---------------------------------------------------------------------------
# _ensure_standard_columns
# ---------------------------------------------------------------------------

class TestEnsureStandardColumns:
    def test_adds_missing_columns(self):
        df = pd.DataFrame({"Name": ["P1"], "Code": ["HC"]})
        result = _ensure_standard_columns(df)
        for col in STANDARD_COLUMNS:
            assert col in result.columns

    def test_numeric_defaults(self):
        df = pd.DataFrame({"Name": ["P1"]})
        result = _ensure_standard_columns(df)
        import math
        assert math.isnan(result.iloc[0]["Easting"])

    def test_string_defaults(self):
        df = pd.DataFrame({"Name": ["P1"]})
        result = _ensure_standard_columns(df)
        assert result.iloc[0]["Code"] == ""
        assert result.iloc[0]["Description"] == ""

    def test_existing_columns_untouched(self):
        df = pd.DataFrame({"Name": ["P1"], "Code": ["HC"], "Easting": [100.0],
                           "Northing": [200.0], "Elevation": [50.0], "Description": ["test"]})
        result = _ensure_standard_columns(df)
        assert result.iloc[0]["Code"] == "HC"
        assert result.iloc[0]["Easting"] == 100.0


# ---------------------------------------------------------------------------
# read_emlid_csv
# ---------------------------------------------------------------------------

class TestReadEmlidCsv:
    def test_loads_rows(self):
        path = _write_tmp(EMLID_CSV_CONTENT, ".csv")
        try:
            df = read_emlid_csv(path)
            assert len(df) == 3
        finally:
            os.unlink(path)

    def test_numeric_columns(self):
        path = _write_tmp(EMLID_CSV_CONTENT, ".csv")
        try:
            df = read_emlid_csv(path)
            assert pd.api.types.is_float_dtype(df["Easting"])
            assert pd.api.types.is_float_dtype(df["Northing"])
            assert pd.api.types.is_float_dtype(df["Elevation"])
        finally:
            os.unlink(path)

    def test_standard_columns_present(self):
        path = _write_tmp(EMLID_CSV_CONTENT, ".csv")
        try:
            df = read_emlid_csv(path)
            for col in STANDARD_COLUMNS:
                assert col in df.columns, f"Missing column: {col}"
        finally:
            os.unlink(path)

    def test_bom_handling(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"\xef\xbb\xbf")  # UTF-8 BOM
            fh.write(EMLID_CSV_CONTENT.encode("utf-8"))
        try:
            df = read_emlid_csv(path)
            assert "Name" in df.columns
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# read_penzd_csv
# ---------------------------------------------------------------------------

class TestReadPenzdCsv:
    def test_loads_rows(self):
        path = _write_tmp(PENZD_CSV_CONTENT, ".csv")
        try:
            df = read_penzd_csv(path)
            assert len(df) == 2
        finally:
            os.unlink(path)

    def test_origin_local(self):
        path = _write_tmp(PENZD_CSV_CONTENT, ".csv")
        try:
            df = read_penzd_csv(path)
            assert (df["Origin"] == "Local").all()
        finally:
            os.unlink(path)

    def test_code_derived_from_name(self):
        path = _write_tmp(PENZD_CSV_CONTENT, ".csv")
        try:
            df = read_penzd_csv(path)
            assert "HC" in df["Code"].values
            assert "PC" in df["Code"].values
        finally:
            os.unlink(path)

    def test_elevation_column_normalised(self):
        content = "Point,Easting,Northing,Elev,Desc\nP1,10,20,50,note\n"
        path = _write_tmp(content, ".csv")
        try:
            df = read_penzd_csv(path)
            assert "Elevation" in df.columns
            assert df.iloc[0]["Elevation"] == 50.0
        finally:
            os.unlink(path)

    def test_numeric_coordinates(self):
        path = _write_tmp(PENZD_CSV_CONTENT, ".csv")
        try:
            df = read_penzd_csv(path)
            assert df.iloc[0]["Easting"] == 100.0
            assert df.iloc[0]["Northing"] == 200.0
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# _auto_csv
# ---------------------------------------------------------------------------

class TestAutoCsv:
    def test_routes_emlid(self):
        path = _write_tmp(EMLID_CSV_CONTENT, ".csv")
        try:
            df = _auto_csv(path)
            assert "Code" in df.columns
            assert len(df) == 3
        finally:
            os.unlink(path)

    def test_routes_penzd(self):
        path = _write_tmp(PENZD_CSV_CONTENT, ".csv")
        try:
            df = _auto_csv(path)
            assert (df["Origin"] == "Local").all()
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# read_kml
# ---------------------------------------------------------------------------

class TestReadKml:
    def test_loads_point_placemarks(self):
        path = _write_tmp(KML_CONTENT, ".kml")
        try:
            df = read_kml(path)
            assert len(df) == 2
        finally:
            os.unlink(path)

    def test_skips_non_point(self):
        # The LineString Placemark in KML_CONTENT should be skipped
        path = _write_tmp(KML_CONTENT, ".kml")
        try:
            df = read_kml(path)
            assert "Line1" not in df["Name"].values
        finally:
            os.unlink(path)

    def test_names_extracted(self):
        path = _write_tmp(KML_CONTENT, ".kml")
        try:
            df = read_kml(path)
            assert "HC-1" in df["Name"].values
            assert "GR-1" in df["Name"].values
        finally:
            os.unlink(path)

    def test_coordinates_extracted(self):
        path = _write_tmp(KML_CONTENT, ".kml")
        try:
            df = read_kml(path)
            row = df[df["Name"] == "HC-1"].iloc[0]
            assert abs(row["Longitude"] - (-97.12300)) < 1e-5
            assert abs(row["Latitude"] - 30.25700) < 1e-5
            assert abs(row["Elevation"] - 202.5) < 1e-5
        finally:
            os.unlink(path)

    def test_origin_global(self):
        path = _write_tmp(KML_CONTENT, ".kml")
        try:
            df = read_kml(path)
            assert (df["Origin"] == "Global").all()
        finally:
            os.unlink(path)

    def test_standard_columns_present(self):
        path = _write_tmp(KML_CONTENT, ".kml")
        try:
            df = read_kml(path)
            for col in STANDARD_COLUMNS:
                assert col in df.columns
        finally:
            os.unlink(path)

    def test_kml_without_namespace(self):
        bare = textwrap.dedent("""\
            <?xml version="1.0"?>
            <kml>
              <Document>
                <Placemark>
                  <name>PT1</name>
                  <Point><coordinates>-90.0,30.0,100.0</coordinates></Point>
                </Placemark>
              </Document>
            </kml>
        """)
        path = _write_tmp(bare, ".kml")
        try:
            df = read_kml(path)
            assert len(df) == 1
            assert df.iloc[0]["Name"] == "PT1"
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# read_shapefile / read_shapefile_zip
# ---------------------------------------------------------------------------

def _make_shp_zip() -> str:
    """Create a minimal in-memory shapefile zip. Returns path to .zip file."""
    try:
        import shapefile
    except ImportError:
        pytest.skip("pyshp not installed")

    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)

    with tempfile.TemporaryDirectory() as tmpdir:
        shp_base = os.path.join(tmpdir, "survey")
        w = shapefile.Writer(shp_base, shapeType=11)  # PointZ
        w.field("Name", "C", 40)
        w.field("Code", "C", 10)
        w.field("Easting", "N", 16, 4)
        w.field("Northing", "N", 16, 4)
        w.field("Elevation", "N", 12, 4)
        w.field("Description", "C", 80)
        w.field("Origin", "C", 10)
        w.pointz(621050.0, 3348120.0, 201.0)
        w.record("CP-1", "CP", 621050.0, 3348120.0, 201.0, "Control", "Global")
        w.pointz(621080.0, 3348150.0, 202.5)
        w.record("HC-1", "HC", 621080.0, 3348150.0, 202.5, "House corner", "Global")
        w.close()

        with zipfile.ZipFile(zip_path, "w") as zf:
            for ext in (".shp", ".dbf", ".shx"):
                zf.write(shp_base + ext, arcname="survey" + ext)

    return zip_path


class TestReadShapefile:
    def test_read_shapefile_zip_loads_rows(self):
        zip_path = _make_shp_zip()
        try:
            df = read_shapefile_zip(zip_path)
            assert len(df) == 2
        finally:
            os.unlink(zip_path)

    def test_shapefile_columns(self):
        zip_path = _make_shp_zip()
        try:
            df = read_shapefile_zip(zip_path)
            for col in STANDARD_COLUMNS:
                assert col in df.columns
        finally:
            os.unlink(zip_path)

    def test_shapefile_values(self):
        zip_path = _make_shp_zip()
        try:
            df = read_shapefile_zip(zip_path)
            row = df[df["Name"] == "CP-1"].iloc[0]
            assert row["Code"] == "CP"
            assert abs(row["Easting"] - 621050.0) < 1e-3
        finally:
            os.unlink(zip_path)

    def test_zip_without_shp_raises(self):
        fd, zip_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "no shapefile here")
        try:
            with pytest.raises(ValueError, match="No Shapefile"):
                read_shapefile_zip(zip_path)
        finally:
            os.unlink(zip_path)


# ---------------------------------------------------------------------------
# read_file — routing
# ---------------------------------------------------------------------------

class TestReadFileRouting:
    def test_routes_csv(self):
        path = _write_tmp(EMLID_CSV_CONTENT, ".csv")
        try:
            df = read_file(path)
            assert len(df) == 3
        finally:
            os.unlink(path)

    def test_routes_kml(self):
        path = _write_tmp(KML_CONTENT, ".kml")
        try:
            df = read_file(path)
            assert len(df) == 2
        finally:
            os.unlink(path)

    def test_routes_zip(self):
        zip_path = _make_shp_zip()
        try:
            df = read_file(zip_path)
            assert len(df) == 2
        finally:
            os.unlink(zip_path)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            read_file("/nonexistent/path/to/file.csv")

    def test_unsupported_extension_raises(self):
        path = _write_tmp("data", ".xyz")
        try:
            with pytest.raises(ValueError, match="Unrecognised"):
                read_file(path)
        finally:
            os.unlink(path)
