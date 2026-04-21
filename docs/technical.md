# Technical Reference

## 6-Stage Pipeline

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Stage 1     │    │  Stage 2     │    │  Stage 3     │
│  Load CSV    │───▶│  Parse       │───▶│  Reproject   │
│  (UTF-8 BOM) │    │  Feature     │    │  WGS84 →     │
│              │    │  Codes       │    │  Target CRS  │
└──────────────┘    └──────────────┘    └──────┬───────┘
                                               │
┌──────────────┐    ┌──────────────┐    ┌──────▼───────┐
│  Stage 6     │    │  Stage 5     │    │  Stage 4     │
│  Write DXF   │◀───│  Unit        │◀───│  Localize    │
│  + PENZD CSV │    │  Conversion  │    │  (Rigid Body │
│              │    │  m → ft      │    │   Transform) │
└──────────────┘    └──────────────┘    └──────────────┘
```

### Stage 1: CSV Loading

- Encoding: `utf-8-sig` to strip the UTF-8 BOM that Emlid Flow sometimes writes
- All column names are stripped of leading/trailing whitespace
- Numeric columns (`Easting`, `Northing`, `Elevation`, `Longitude`, `Latitude`,
  `Ellipsoidal height`) are coerced to float; invalid values become `NaN`
- A full validation pass runs immediately after load (see Validation section below)

### Stage 2: Feature Code Parsing

The `Code` column is split into:

- `base_code`: the alphabetic prefix (e.g. `PC` from `PC-2`)
- `code_number`: the trailing integer (e.g. `2` from `PC-2`)

Pattern: `^([A-Za-z]+)[^0-9]*(\d+)?$`

Unknown codes fall back to the `V-NODE` layer with a console warning.

### Stage 3: Coordinate Reprojection

Uses **pyproj** `Transformer.from_crs(source, target, always_xy=True)`.

When `source_crs = EPSG:4326`, the `Longitude` / `Latitude` columns are used
as inputs (decimal degrees, WGS84). For any other source CRS, `Easting` and
`Northing` are used.

The `always_xy=True` flag ensures longitude is always treated as X and latitude
as Y, regardless of the authority-defined axis order of the CRS.

### Stage 4: 2D Localization

See the Localization Math section below.

### Stage 5: Unit Conversion

**Meters → US Survey Feet (exact):**

```
1 US survey foot = 1200 / 3937 meters (exact by US definition)
1 meter = 3937 / 1200 US survey feet = 3.28083333... ft
```

This factor is applied to `Easting`, `Northing`, and `Elevation`.

The Z datum offset (if any) is applied **before** unit conversion so it can be
specified in meters regardless of output units.

### Stage 6: DXF Writing

See DXF Output section below.

---

## Localization Math

### Two-Point Rigid Body Transform

Given two source points `(x1s, y1s)`, `(x2s, y2s)` and their known target
coordinates `(x1t, y1t)`, `(x2t, y2t)`:

```
dx_s = x2s - x1s,  dy_s = y2s - y1s      (source vector)
dx_t = x2t - x1t,  dy_t = y2t - y1t      (target vector)

angle_s = atan2(dy_s, dx_s)
angle_t = atan2(dy_t, dx_t)
θ = angle_t - angle_s                      (rotation angle)
scale = |target vector| / |source vector|  (should be ≈1 for same units)

a = scale · cos(θ),   b = scale · sin(θ)
tx = x1t - (a·x1s - b·y1s)
ty = y1t - (b·x1s + a·y1s)
```

Transform applied to any point `(x, y)`:

```
x' = a·x - b·y + tx
y' = b·x + a·y + ty
```

For exactly two control points, residuals are identically 0.

### Helmert Least-Squares Transform (N ≥ 2)

The same model `(x', y') = f(a, b, tx, ty)` is written as a linear system:

```
For each control point i:
    [ xsi  -ysi  1  0 ] [ a  ]   [ xti ]
    [ ysi   xsi  0  1 ] [ b  ] = [ yti ]
                        [ tx ]
                        [ ty ]
```

With N point pairs, the design matrix A is `2N × 4`. The solution minimizes
`‖Ax - b‖²` via `numpy.linalg.lstsq`. Scale and rotation are recovered as:

```
scale = sqrt(a² + b²)
θ     = atan2(b, a)
```

Per-point residuals are `r_i = sqrt((x'_i - x_ti)² + (y'_i - y_ti)²)`.
RMS = `sqrt(Σ r_i² / N)`.

---

## DXF Output

### Header Variables

| Variable | Value | Effect |
|----------|-------|--------|
| `$INSUNITS` | `2` | Decimal feet (Pool Studio requirement) |
| `$PDMODE` | `35` | Point symbol: X inside circle |
| `$PDSIZE` | `0.5` | Point symbol size in drawing units |
| `$LTSCALE` | `0.5` | Line type scale |

### Entity Types Used

| DXF Entity | Usage |
|-----------|-------|
| `POINT` | Every survey point |
| `TEXT` | Point name labels, elevation callouts |
| `CIRCLE` | Tree drip lines |
| `LWPOLYLINE` | Property boundary, house footprint |

### Layer Structure (AIA NCS V6)

All layers are created at document open, regardless of whether any points use
them. This ensures the layer palette is consistent in Pool Studio.

### Text Placement

Labels are offset `+0.3 ft` in both X and Y from the point coordinate so they
do not overlap the point symbol. Elevation callouts (GR shots) are placed
`-text_height ft` below the point to stay visually distinct from the name label.

---

## Validation

Poolbridge performs these checks:

| Check | Severity | Description |
|-------|----------|-------------|
| Required columns present | Error | Stops conversion if Name, Code, Easting, Northing, or Elevation are missing |
| Duplicate point names | Warning | All duplicates kept; downstream auto-connect may be unpredictable |
| Negative elevations | Warning | Suggests ellipsoidal heights without geoid correction |
| E/N < 1.0 range | Warning | May indicate geographic coordinates (degrees) in E/N columns |
| Control points in CSV | Error | Stops localization if named control points are absent |
| Control point separation < 1m | Warning | Poor geometry for localization |
| Localization RMS > 0.1 ft | Warning | Check control point coordinates for blunders |

---

## Known Limitations

1. **No geoid correction**: Poolbridge does not apply GEOID18 or EGM96 corrections.
   If your Emlid project uses ellipsoidal heights, apply a manual Z offset equal
   to the local geoid undulation. In Texas, this is typically −22 to −27 m.

2. **No 3D polylines**: House and property outlines are written as 2D `LWPOLYLINE`
   entities with no Z component. The Z coordinate of individual `POINT` entities
   is preserved.

3. **Single CRS per file**: All points in a single CSV must share the same origin
   CRS. Mixed-CRS files are not supported.

4. **Arc/curve features**: Curved pool walls or arcs in property boundaries are
   not drawn automatically. These require manual drafting in Pool Studio after import.

5. **Scale factor**: The two-point and Helmert transforms solve for scale, but
   a scale significantly different from 1.0 indicates a problem (usually a units
   mismatch). A warning is issued, but the scaled coordinates are still written.

6. **Pandas 2.x nullable types**: The `code_number` column uses `object` dtype
   to hold a mix of `int` and `None` values. This is intentional and consistent
   with Pandas 2.x nullable integer handling.
