# Configuration Reference

## Config File Format

Poolbridge accepts YAML or JSON config files. YAML is recommended for readability.

```bash
poolbridge convert survey.csv -c my_config.yaml -o output.dxf
```

---

## Top-Level Sections

### `coordinate_system`

```yaml
coordinate_system:
  source_crs: "EPSG:4326"    # Input CRS (default: WGS84)
  target_crs: "EPSG:32614"   # Output projected CRS
```

When `source_crs` is `EPSG:4326` (WGS84), poolbridge uses the `Longitude` and
`Latitude` columns for reprojection. For any other source CRS, `Easting` and
`Northing` are used directly.

**Common `target_crs` values:**

| Region | EPSG | Description |
|--------|------|-------------|
| Texas Central | `EPSG:32614` | UTM Zone 14N |
| Texas East | `EPSG:32615` | UTM Zone 15N |
| TX State Plane Central | `EPSG:2277` | NAD83, US survey feet |
| TX State Plane South Central | `EPSG:2278` | NAD83, US survey feet |
| FL State Plane East | `EPSG:2238` | NAD83, US survey feet |
| CA Zone III | `EPSG:2227` | NAD83, US survey feet |

Find your zone at: [spatialreference.org](https://spatialreference.org) or
[epsg.io](https://epsg.io)

---

### `units`

```yaml
units:
  convert_to_feet: true    # multiply E/N/Z by 3937/1200 (US survey feet)
```

Set `convert_to_feet: false` if your target CRS already outputs in feet
(e.g. Texas State Plane in US survey feet) or if you want a metric DXF.

---

### `localization`

```yaml
localization:
  method: "two_point"    # "two_point" or "helmert"

  control_points:
    - name: "CP-1"           # Exact match to the Name column in your CSV
      known_easting: 0.0     # Design/deed easting in meters (pre-unit-conversion)
      known_northing: 0.0    # Design/deed northing in meters

    - name: "CP-2"
      known_easting: 30.0
      known_northing: 0.0
```

Leave `control_points: []` to skip localization and use projected CRS coordinates
directly in the output.

**`method` options:**

| Value | Points Required | Description |
|-------|----------------|-------------|
| `two_point` | Exactly 2 | Exact rigid-body transform through both points |
| `helmert` | 2 or more | Least-squares similarity transform with residuals |

The `helmert` method is automatically used when 3 or more control points are
provided regardless of the `method` setting.

---

### `z_datum`

```yaml
z_datum:
  method: "offset"    # "offset" or "point"
  offset: 0.0         # Meters added to every elevation (can be negative)
```

**Using a reference point for elevation zero:**

```yaml
z_datum:
  method: "point"
  reference_point: "FF-1"   # Name of the point whose elevation becomes 0.00
```

The offset is computed as `-elevation_of_reference_point` so that point ends up
at elevation 0.00 after adjustment.

---

### `output`

```yaml
output:
  dxf_version: "R2010"    # DXF version string (R2010 is broadly compatible)
  pdmode: 35              # PDMODE: point symbol style (35 = X in circle)
  pdsize: 0.5             # Point symbol size in output units
  text_height: 0.5        # Label text height in output units
  export_penzd_csv: true  # Write a secondary PENZD CSV alongside the DXF
```

**Common PDMODE values:**

| Value | Symbol |
|-------|--------|
| 0 | Dot (default) |
| 3 | × (cross) |
| 35 | X inside circle (recommended for Pool Studio) |
| 34 | + inside circle |

---

### `feature_codes`

Map survey codes to DXF layers and drawing behaviours:

```yaml
feature_codes:
  CODE:
    layer: "V-LAYER-NAME"   # DXF layer (created automatically if missing)
    color: 7                # AutoCAD Color Index (ACI), 1–256
    description: "Human readable label"

    # Optional behaviours:
    auto_connect: true      # Draw closed polyline through numbered sequence
    label_elevation: true   # Place elevation value as TEXT near point
    label_prefix: "FFE="    # Prepend this string to the elevation label
    draw_drip_circle: true  # Parse diameter from Description and draw CIRCLE
```

**AutoCAD Color Index (ACI) quick reference:**

| Value | Color |
|-------|-------|
| 1 | Red |
| 2 | Yellow |
| 3 | Green |
| 4 | Cyan |
| 5 | Blue |
| 6 | Magenta |
| 7 | White |

---

## Standard Pool Survey Codes

| Code | Layer | Behaviour | Description |
|------|-------|-----------|-------------|
| `HC` | `V-BLDG` | Auto-connect | House corner |
| `PC` | `V-PROP` | Auto-connect | Property corner |
| `GR` | `V-TOPO-SPOT` | Elevation label | Grade shot |
| `TR` | `V-PLNT-TREE` | Drip circle | Tree |
| `FF` | `V-NODE` | `FFE=` label | Finished floor elevation |
| `CP` | `V-SURV-CTRL` | — | Control point |
| `BM` | `V-SURV-CTRL` | Elevation label | Benchmark |
| `EL` | `V-UTIL-ELEC` | — | Electric |
| `EP` | `V-UTIL-ELEC` | — | Electric pole |
| `GA` | `V-UTIL-GAS` | — | Gas |
| `WA` | `V-UTIL-WATR` | — | Water |
| `SE` | `V-UTIL-SEWR` | — | Sewer |
| `CB` | `V-UTIL-SEWR` | — | Catch basin |
| `MH` | `V-UTIL-SEWR` | — | Manhole |

---

## AIA NCS Layer Names

Poolbridge uses **AIA National CAD Standards V6** layer naming:

| Layer | Color | Contents |
|-------|-------|----------|
| `V-NODE` | White | Survey points (generic) |
| `V-NODE-TEXT` | White | Point name labels |
| `V-PROP` | Red | Property lines and corners |
| `V-BLDG` | White | Building/house footprint |
| `V-TOPO-SPOT` | Cyan | Spot elevations |
| `V-PLNT-TREE` | Green | Trees and drip circles |
| `V-UTIL-ELEC` | Yellow | Electrical utilities |
| `V-UTIL-GAS` | Magenta | Gas utilities |
| `V-UTIL-WATR` | Blue | Water utilities |
| `V-UTIL-SEWR` | Green | Sewer/drainage utilities |
| `V-SURV-CTRL` | Magenta | Control points and benchmarks |

---

## Tree Drip Circle Diameter Formats

When `draw_drip_circle: true`, poolbridge parses the `Description` column for
diameter values in any of these formats:

```
D=14'          D = 14'        D=14ft
D=4.27m        DIA=14         DIA:14
14' dia        14' DIA
```

The diameter is halved to produce a radius, and a `CIRCLE` entity is placed on
the `V-PLNT-TREE` layer centred at the tree point location.

---

## Auto-Connect Rules

When `auto_connect: true`, poolbridge collects all points sharing the same base
code and connects them in numerical order with a closed `LWPOLYLINE`:

- `PC-1`, `PC-2`, `PC-3`, `PC-4` → property boundary rectangle
- `HC-1`, `HC-2`, `HC-3`, `HC-4` → house footprint rectangle

The points are sorted by the trailing number in the code (`PC-1` → 1, etc.).
If no number is present, they are sorted alphabetically by `Name`.

To skip auto-connect for a specific set of points, omit `auto_connect` or set
it to `false` in that code's config entry.
