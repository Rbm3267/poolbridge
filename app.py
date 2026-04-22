"""Streamlit web interface for poolbridge."""

import os
import tempfile

import pandas as pd
import streamlit as st
import yaml

from poolbridge.converter import PoolBridgeConverter
from poolbridge.readers import read_file

st.set_page_config(
    page_title="Poolbridge",
    page_icon="assets/poolbridge-icon-512.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── SIDEBAR ─────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #111B27;
    border-right: 1px solid #1E2D3D;
}

/* Text */
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] .stMarkdown {
    color: #E8EFF6 !important;
}
[data-testid="stSidebar"] .stCaption p {
    color: #7B9BB5 !important;
    font-size: 0.8rem !important;
}

/* Divider */
[data-testid="stSidebar"] hr {
    border-color: #2E4159 !important;
}

/* Selectbox — dark background, white text */
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background-color: #1A2A3A !important;
    border-color: #2E4159 !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] span,
[data-testid="stSidebar"] [data-baseweb="select"] div {
    color: #E8EFF6 !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] svg {
    fill: #7B9BB5 !important;
}

/* Text + number inputs */
[data-testid="stSidebar"] input {
    background-color: #1A2A3A !important;
    border-color: #2E4159 !important;
    border-radius: 8px !important;
    color: #E8EFF6 !important;
}
[data-testid="stSidebar"] [data-baseweb="input"] {
    background-color: #1A2A3A !important;
    border-color: #2E4159 !important;
}

/* Expanders */
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    background-color: #1A2A3A !important;
    border: 1px solid #2E4159 !important;
    border-radius: 8px !important;
    color: #E8EFF6 !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] > div:last-child {
    background-color: #152030 !important;
    border: 1px solid #2E4159 !important;
    border-radius: 0 0 8px 8px !important;
}

/* Radio + checkbox labels */
[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] .stCheckbox label {
    color: #E8EFF6 !important;
}

/* ── MAIN AREA ───────────────────────────────────────────── */
/* Primary convert button */
button[kind="primary"] {
    background: linear-gradient(135deg, #2EC4B6 0%, #0E7FA3 100%) !important;
    border: none !important;
    color: #FFFFFF !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    letter-spacing: 0.02em !important;
    padding: 0.55rem 2rem !important;
    transition: opacity 0.15s, box-shadow 0.15s !important;
}
button[kind="primary"]:hover {
    opacity: 0.9 !important;
    box-shadow: 0 4px 14px rgba(46,196,182,0.35) !important;
}

/* File uploader area */
[data-testid="stFileUploader"] section {
    border: 2px dashed #2E4159 !important;
    border-radius: 12px !important;
}
[data-testid="stFileUploader"] section:hover {
    border-color: #2EC4B6 !important;
    background-color: rgba(46,196,182,0.04) !important;
}

/* Download buttons */
[data-testid="stDownloadButton"] button {
    border-radius: 8px !important;
    font-weight: 500 !important;
}

/* Alert / success boxes */
[data-testid="stAlert"] {
    border-radius: 10px !important;
}

/* Headers */
h1, h2, h3 { letter-spacing: -0.01em !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar — settings
# ---------------------------------------------------------------------------

with st.sidebar:
    st.image("assets/poolbridge-mark-wordmark-dark.png", use_container_width=True)
    st.divider()

    st.subheader("Coordinate System")
    crs_options = {
        # --- Gulf Coast / South Central ---
        "UTM Zone 13N — west Texas / New Mexico": "EPSG:32613",
        "UTM Zone 14N — central Texas": "EPSG:32614",
        "UTM Zone 15N — east Texas / Louisiana": "EPSG:32615",
        "TX State Plane Central (US ft)": "EPSG:2277",
        "TX State Plane S. Central (US ft)": "EPSG:2278",
        "TX State Plane South (US ft)": "EPSG:2279",
        # --- Southeast ---
        "UTM Zone 16N — AL, MS, FL Panhandle, TN, KY, western GA": "EPSG:32616",
        "UTM Zone 17N — FL Peninsula, GA, SC, NC, VA (central/western)": "EPSG:32617",
        "UTM Zone 18N — NC, VA (eastern / coast)": "EPSG:32618",
        "NC State Plane (US ft)": "EPSG:2264",
        "SC State Plane (US ft)": "EPSG:2273",
        "VA State Plane North (US ft)": "EPSG:2283",
        "VA State Plane South (US ft)": "EPSG:2284",
        "GA State Plane West (US ft)": "EPSG:2239",
        "GA State Plane East (US ft)": "EPSG:2240",
        # --- Florida ---
        "FL State Plane East (US ft)": "EPSG:2236",
        "FL State Plane West (US ft)": "EPSG:2237",
        "FL State Plane North (US ft)": "EPSG:2238",
        # --- West Coast ---
        "CA Zone III (US ft)": "EPSG:2227",
        # --- Custom ---
        "Custom EPSG…": "custom",
    }
    crs_label = st.selectbox("Target CRS", list(crs_options.keys()))
    if crs_options[crs_label] == "custom":
        crs_code = st.text_input("EPSG code", placeholder="EPSG:32614")
    else:
        crs_code = crs_options[crs_label]
        st.caption(f"`{crs_code}`")

    convert_to_feet = st.checkbox(
        "Convert to US survey feet",
        value=True,
        help="Uncheck if your CRS already outputs in feet (State Plane US ft zones).",
    )

    st.divider()
    st.subheader("Localization")
    st.caption("Match survey control points to known site coordinates.")

    num_cp = st.number_input(
        "Number of control points", min_value=0, max_value=6, value=2, step=1
    )
    control_points = []
    for i in range(int(num_cp)):
        with st.expander(f"Control Point {i + 1}", expanded=True):
            name = st.text_input("Name in CSV", key=f"cp_name_{i}", placeholder="CP-1")
            col1, col2 = st.columns(2)
            known_e = col1.number_input("Known Easting", key=f"cp_e_{i}", value=0.0, format="%.3f")
            known_n = col2.number_input("Known Northing", key=f"cp_n_{i}", value=0.0, format="%.3f")
            if name.strip():
                control_points.append({
                    "name": name.strip(),
                    "known_easting": known_e,
                    "known_northing": known_n,
                })

    st.divider()
    st.subheader("Z Datum")
    z_method = st.radio(
        "Set elevation zero from",
        ["Leave as measured", "Named point (e.g. finished floor)", "Fixed offset"],
        label_visibility="collapsed",
    )
    z_datum_cfg: dict = {"method": "offset", "offset": 0.0}
    if z_method == "Named point (e.g. finished floor)":
        ref = st.text_input("Point name", placeholder="FF-1")
        z_datum_cfg = {"method": "point", "reference_point": ref}
    elif z_method == "Fixed offset":
        offset = st.number_input("Offset (meters, added to all elevations)", value=0.0, format="%.4f")
        z_datum_cfg = {"method": "offset", "offset": float(offset)}

    st.divider()
    st.subheader("Contours")
    st.caption(
        "Generate V-TOPO-MAJR / V-TOPO-MINR contour lines from GR (grade shot) points. "
        "Requires ≥ 3 GR shots and scipy."
    )
    contours_enabled = st.checkbox("Generate contour lines", value=False)
    contour_cfg: dict = {"enabled": False}
    if contours_enabled:
        col1, col2 = st.columns(2)
        major_int = col1.number_input("Major interval (ft)", value=1.0, min_value=0.1, format="%.2f")
        minor_int = col2.number_input("Minor interval (ft)", value=0.25, min_value=0.05, format="%.2f")
        contour_cfg = {
            "enabled": True,
            "major_interval": float(major_int),
            "minor_interval": float(minor_int),
            "grid_cells": 150,
        }


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.header("Step 1 — Upload your Emlid survey file")
st.caption(
    "Supported formats: **CSV** (Emlid Flow full export), **PENZD CSV** (.csv/.txt), "
    "**KML** (.kml), **Shapefile** (.zip containing .shp/.dbf/.shx), **DXF** (.dxf)"
)
survey_file = st.file_uploader(
    "Drag and drop your Emlid survey file here",
    type=["csv", "txt", "kml", "zip", "dxf"],
    label_visibility="collapsed",
)

df_preview = None
if survey_file:
    with tempfile.NamedTemporaryFile(
        suffix=os.path.splitext(survey_file.name)[1], delete=False
    ) as tmp:
        tmp.write(survey_file.getvalue())
        tmp_path = tmp.name
    try:
        df_preview = read_file(tmp_path)
        st.success(f"{len(df_preview)} points loaded from **{survey_file.name}**")
        with st.expander("Preview points"):
            st.dataframe(df_preview, use_container_width=True)
    except Exception as exc:
        st.error(f"Could not read file: {exc}")
        df_preview = None
    finally:
        os.unlink(tmp_path)

st.divider()
st.header("Step 2 — Config file (optional)")
st.caption(
    "Upload a poolbridge YAML config for custom feature codes and layer mappings. "
    "If you skip this, the sidebar settings and built-in defaults are used."
)
config_file = st.file_uploader(
    "Config YAML",
    type=["yaml", "yml", "json"],
    label_visibility="collapsed",
)

st.divider()
st.header("Step 3 — Convert")

ready = survey_file is not None and df_preview is not None
if st.button("Convert to DXF", type="primary", disabled=not ready):
    with st.spinner("Running conversion…"):
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Write survey file to temp location preserving extension
                ext = os.path.splitext(survey_file.name)[1]
                input_path = os.path.join(tmpdir, f"input{ext}")
                with open(input_path, "wb") as f:
                    f.write(survey_file.getvalue())

                # Build or write config
                if config_file:
                    config_path = os.path.join(tmpdir, "config.yaml")
                    with open(config_path, "wb") as f:
                        f.write(config_file.getvalue())
                else:
                    cfg = {
                        "coordinate_system": {
                            "source_crs": "EPSG:4326",
                            "target_crs": crs_code or None,
                        },
                        "units": {"convert_to_feet": convert_to_feet},
                        "localization": {
                            "method": "helmert" if len(control_points) >= 3 else "two_point",
                            "control_points": control_points,
                        },
                        "z_datum": z_datum_cfg,
                        "contours": contour_cfg,
                        "output": {
                            "dxf_version": "R2010",
                            "pdmode": 35,
                            "pdsize": 0.5,
                            "text_height": 0.5,
                            "export_penzd_csv": True,
                        },
                    }
                    config_path = os.path.join(tmpdir, "config.yaml")
                    with open(config_path, "w") as f:
                        yaml.dump(cfg, f)

                output_dxf = os.path.join(tmpdir, "output.dxf")
                converter = PoolBridgeConverter(config_path)
                result = converter.convert(input_csv=input_path, output_dxf=output_dxf)

                st.success(
                    f"Done — **{result.point_count} points** converted successfully."
                )

                # Localization report
                if result.localization_report:
                    with st.expander("Localization report", expanded=True):
                        st.code(result.localization_report)

                # Warnings
                if result.warnings:
                    with st.expander(f"{len(result.warnings)} warning(s)"):
                        for w in result.warnings:
                            st.warning(w)

                # Download buttons
                st.subheader("Download outputs")
                col1, col2 = st.columns(2)

                with open(output_dxf, "rb") as f:
                    dxf_bytes = f.read()
                stem = os.path.splitext(survey_file.name)[0]
                col1.download_button(
                    "⬇ Download DXF",
                    dxf_bytes,
                    file_name=f"{stem}.dxf",
                    mime="application/octet-stream",
                    use_container_width=True,
                )

                if result.penzd_path and os.path.exists(result.penzd_path):
                    with open(result.penzd_path, "rb") as f:
                        penzd_bytes = f.read()
                    col2.download_button(
                        "⬇ Download PENZD CSV",
                        penzd_bytes,
                        file_name=f"{stem}_penzd.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

        except Exception as exc:
            st.error(f"Conversion failed: {exc}")
            with st.expander("Details"):
                st.exception(exc)
