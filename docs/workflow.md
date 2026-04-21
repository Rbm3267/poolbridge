# Workflow Guide

## Overview

A typical pool site survey workflow with poolbridge:

```
Emlid Flow app                poolbridge                Pool Studio
─────────────────    ──────────────────────────────    ──────────────
Field survey with  →  CSV → DXF with layers,      →  Import DXF,
RTK GNSS receiver     labels, tree circles,           trace pool
                       property boundaries             on site plan
```

## Step-by-Step

### 1. Export from Emlid Flow

1. Open your project in **Emlid Flow**
2. Tap **Export** → **CSV**
3. Save the `.csv` file to your computer

The CSV will have columns:
`Name, Code, Easting, Northing, Elevation, Description, Longitude, Latitude, Ellipsoidal height, Origin`

### 2. Create a Config File

Copy `examples/sample_config.yaml` and edit it for your project:

```bash
cp examples/sample_config.yaml my_project.yaml
```

Key settings to change:

```yaml
coordinate_system:
  target_crs: "EPSG:32614"   # Change to your UTM zone

localization:
  control_points:
    - name: "CP-1"           # Must match the Name column in your CSV
      known_easting: 0.0     # Your local/design coordinate
      known_northing: 0.0
    - name: "CP-2"
      known_easting: 100.0
      known_northing: 0.0

z_datum:
  method: "point"
  reference_point: "FF-1"   # Use this point's elevation as project 0.00
```

### 3. Run the Conversion

```bash
poolbridge convert survey.csv -c my_project.yaml -o pool_site.dxf
```

**Verbose output** (shows all reprojection and localization steps):
```bash
poolbridge convert survey.csv -c my_project.yaml -o pool_site.dxf -v
```

### 4. Review Localization Output

The console prints a residual report:

```
--- Localization Report ---
  Method : Two-Point
  Points : 2
  Rotation: 12.3456°
  Scale   : 1.000003
  RMS     : 0.0000 ft

  Name         Src E        Src N        Tgt E        Tgt N    Resid
  ----------------------------------------------------------------
  CP-1      621000.000  3348120.000        0.000        0.000   0.0000
  CP-2      621030.000  3348120.000      100.000        0.000   0.0000
--- End Report ---
```

A scale factor significantly different from 1.0 indicates a units mismatch or
poor control point quality.

### 5. Import into Pool Studio

1. **File → New Project** in Pool Studio
2. **Insert → Import → DXF** → select `pool_site.dxf`
3. Set scale to **1:1** and units to **Decimal Feet**
4. Use the **V-PROP** layer as your lot boundary
5. Use the **V-BLDG** layer as the house footprint reference

---

## Coordinate Workflow Options

### Option A: Two-Point Localization (Most Common)

Provide 2 control points (e.g., two property monuments with known deed coordinates):

```yaml
localization:
  method: "two_point"
  control_points:
    - name: "CP-1"
      known_easting: 1523.45    # feet (in design/deed space)
      known_northing: 847.23
    - name: "CP-2"
      known_easting: 1623.45
      known_northing: 847.23
```

This gives an exact fit through both control points. Use it when you trust
both monuments equally.

### Option B: Helmert Least-Squares (3+ Control Points)

With 3 or more control points, poolbridge solves a least-squares similarity
transform and reports residuals for each point. This lets you detect blunders.

```yaml
localization:
  method: "helmert"
  control_points:
    - name: "CP-1"
      known_easting: 0.0
      known_northing: 0.0
    - name: "CP-2"
      known_easting: 100.0
      known_northing: 0.0
    - name: "CP-3"
      known_easting: 50.0
      known_northing: 80.0
```

Residuals above 0.1 ft suggest a measurement error or monument mismatch.

### Option C: No Localization (Use CSV Coordinates Directly)

Skip localization entirely and work in the projected CRS directly:

```bash
poolbridge convert survey.csv --crs EPSG:32614 --no-localize -o output.dxf
```

---

## Z Datum Options

### Option A: Named Reference Point

Set a measured point (e.g., finished floor, benchmark) as elevation 0.00:

```yaml
z_datum:
  method: "point"
  reference_point: "FF-1"
```

All elevations are adjusted relative to that point's measured elevation.

### Option B: Fixed Offset

Subtract a constant from all elevations:

```yaml
z_datum:
  method: "offset"
  offset: -179.845    # subtract 179.845 m from all elevations
```

### Option C: Raw Elevations

Leave `z_datum.offset: 0.0` and all elevations are used as measured (converted
to feet if `units.convert_to_feet: true`).

---

## Using the PENZD CSV

The secondary `*_penzd.csv` export contains your converted/localized coordinates
in Point, Easting, Northing, Z, Description format. Use it to:

- Re-import stakeout points into Emlid Flow for layout
- Compare against design coordinates
- Archive a clean point list for the job file

Import into Emlid Flow: **Project → Import → Custom CSV** → map columns to
Point Name, Easting, Northing, Elevation.
