# Poolbridge Examples

This directory contains a complete sample conversion you can run immediately
to verify your installation.

## Files

| File | Description |
|------|-------------|
| `sample_emlid_export.csv` | Anonymized Emlid Flow CSV from a real pool site survey |
| `sample_config.yaml` | Feature code mapping and localization config for the sample |
| `expected_output.dxf` | Reference DXF produced by running the sample (generated on first run) |

## Running the Sample Conversion

From the repository root:

```bash
cd examples
poolbridge convert sample_emlid_export.csv \
    -c sample_config.yaml \
    -o site_plan.dxf
```

Or using Python directly:

```python
from poolbridge import PoolBridgeConverter

converter = PoolBridgeConverter("examples/sample_config.yaml")
result = converter.convert(
    input_csv="examples/sample_emlid_export.csv",
    output_dxf="examples/site_plan.dxf",
)
print(result)
```

## Expected Output

After conversion you should see output similar to:

```
Conversion complete: 31 points
  DXF   : site_plan.dxf
  PENZD : site_plan_penzd.csv
--- Localization Report ---
  Method : Two-Point
  Points : 2
  Rotation: 0.0000°
  Scale   : 1.000000
  RMS     : 0.0000 ft
  ...
--- End Report ---
```

Two output files are created:

- **`site_plan.dxf`** — Open in AutoCAD, Vectorworks, or Pool Studio
- **`site_plan_penzd.csv`** — Point list for stakeout re-import into Emlid Flow

## Verifying in AutoCAD / Vectorworks

1. Open `site_plan.dxf`
2. Run `ZOOM > EXTENTS` to see all points
3. Open the **Layers** panel — you should see:
   - `V-BLDG` (white) — house footprint polyline + corners
   - `V-PROP` (red) — property boundary polyline + corners
   - `V-TOPO-SPOT` (cyan) — grade shots with elevation labels
   - `V-PLNT-TREE` (green) — tree points with drip-line circles
   - `V-NODE-TEXT` (white) — all point name labels
   - `V-UTIL-*` — utility points by type
   - `V-SURV-CTRL` (magenta) — control points and benchmarks

## Verifying in Pool Studio

1. Open Pool Studio → New Project
2. **Import → DXF/DWG** → select `site_plan.dxf`
3. Set units to **Decimal Feet** if prompted (the file declares `$INSUNITS=2`)
4. The house outline should appear on the canvas at correct scale
5. Use the property boundary as your lot outline reference

## Sample Site Layout

```
N
^
|    PC-4─────────────────────PC-3
|    │    TR-1                  │
|    │  HC-4────────HC-3        │
|    │  │    FF-1   │           │
|    │  │           │           │
|    │  HC-1────────HC-2        │
|    │          TR-2 TR-3       │
|    PC-1─────────────────────PC-2
|        WA GA SE CB
└────────────────────────────────> E
    (30m × 45m lot, ~100ft × 148ft)
```

## Customizing the Config

Edit `sample_config.yaml` to:

- Change `target_crs` to match your UTM zone or State Plane
- Update `localization.control_points` with your monument coordinates
- Change `z_datum.reference_point` to set a different project elevation baseline
- Add custom feature codes for your organization's survey codes
