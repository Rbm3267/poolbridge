"""Streamlit web interface for poolbridge."""

import os
import tempfile

import pandas as pd
import streamlit as st
import yaml

from poolbridge.converter import PoolBridgeConverter

st.set_page_config(
    page_title="Poolbridge",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar — settings
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Poolbridge")
    st.caption("Emlid survey → Pool Studio DXF")
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
        "UTM Zone 16N — AL, MS, TN, KY, western GA": "EPSG:32616",
        "UTM Zone 17N — GA, SC, NC, VA (central/western)": "EPSG:32617",
        "UTM Zone 18N — NC, VA (eastern / coast)": "EPSG:32618",
        "NC State Plane (US ft)": "EPSG:2264",
        "VA State Plane North (US ft)": "EPSG:2283",
        "VA State Plane South (US ft)": "EPSG:2284",
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


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

st.header("Step 1 — Upload your Emlid CSV")
csv_file = st.file_uploader(
    "Drag and drop your Emlid Flow CSV export here",
    type=["csv"],
    label_visibility="collapsed",
)

df_preview = None
if csv_file:
    df_preview = pd.read_csv(csv_file, encoding="utf-8-sig", dtype=str)
    csv_file.seek(0)
    st.success(f"{len(df_preview)} points loaded from **{csv_file.name}**")
    with st.expander("Preview points"):
        st.dataframe(df_preview, use_container_width=True)

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

ready = csv_file is not None
if st.button("Convert to DXF", type="primary", disabled=not ready):
    with st.spinner("Running conversion…"):
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Write CSV to temp file
                csv_path = os.path.join(tmpdir, "input.csv")
                with open(csv_path, "wb") as f:
                    f.write(csv_file.getvalue())

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
                result = converter.convert(input_csv=csv_path, output_dxf=output_dxf)

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
                stem = os.path.splitext(csv_file.name)[0]
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
