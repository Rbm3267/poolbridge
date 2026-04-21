# Setup Guide

## Requirements

- Python 3.8 or later
- pip

## Installation

### From PyPI (once published)

```bash
pip install poolbridge
```

### From Source

```bash
git clone https://github.com/rbm3267/poolbridge.git
cd poolbridge
pip install -e .
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `ezdxf` | ≥1.1.0 | DXF file generation |
| `pyproj` | ≥3.4.0 | Coordinate system transformations |
| `pandas` | ≥1.5.0 | CSV parsing and data manipulation |
| `pyyaml` | ≥6.0 | Config file parsing |
| `numpy` | ≥1.23.0 | Matrix math for Helmert localization |

Install dependencies manually if needed:

```bash
pip install ezdxf pyproj pandas pyyaml numpy
```

## Verification

```bash
poolbridge --version
# poolbridge 0.1.0

python -c "from poolbridge import PoolBridgeConverter; print('OK')"
# OK
```

## Quick Smoke Test

```bash
cd examples
poolbridge convert sample_emlid_export.csv -c sample_config.yaml -o test_output.dxf
# Conversion complete: 31 points
#   DXF   : test_output.dxf
#   PENZD : test_output_penzd.csv
```

## Troubleshooting

**`ModuleNotFoundError: No module named 'pyproj'`**
The PROJ library may need a system-level install on some Linux distributions:
```bash
sudo apt-get install proj-bin libproj-dev   # Debian/Ubuntu
brew install proj                            # macOS
```
Then: `pip install pyproj`

**`ImportError` on Windows with ezdxf**
Ensure you are using Python 3.8+ (not 2.x). ezdxf dropped Python 2 support in v0.14.

**`FileNotFoundError: Config file not found`**
Use an absolute path or run poolbridge from the directory containing your config file.
