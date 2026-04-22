"""Configuration loading and validation for poolbridge feature code mappings."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

# Default layer colors using AutoCAD Color Index (ACI)
_ACI_WHITE = 7
_ACI_RED = 1
_ACI_YELLOW = 2
_ACI_GREEN = 3
_ACI_CYAN = 4
_ACI_BLUE = 5
_ACI_MAGENTA = 6

DEFAULT_CONFIG: Dict[str, Any] = {
    "coordinate_system": {
        "source_crs": "EPSG:4326",
        "target_crs": None,  # If None, use E/N from CSV directly
    },
    "units": {
        "convert_to_feet": True,
    },
    "localization": {
        "method": "two_point",  # "two_point" or "helmert"
        "control_points": [],
    },
    "z_datum": {
        "method": "offset",  # "offset" or "point"
        "offset": 0.0,
        "reference_point": None,
    },
    "output": {
        "dxf_version": "R2010",
        "pdmode": 35,
        "pdsize": 0.5,
        "text_height": 0.5,
        "export_penzd_csv": True,
    },
    "contours": {
        "enabled": False,
        "major_interval": 1.0,   # feet
        "minor_interval": 0.25,  # feet
        "grid_cells": 150,
    },
    "feature_codes": {
        "HC": {
            "layer": "V-BLDG",
            "color": _ACI_WHITE,
            "description": "House corner",
            "auto_connect": True,
        },
        "PC": {
            "layer": "V-PROP",
            "color": _ACI_RED,
            "description": "Property corner",
            "auto_connect": True,
        },
        "GR": {
            "layer": "V-TOPO-SPOT",
            "color": _ACI_CYAN,
            "description": "Grade shot",
            "label_elevation": True,
        },
        "TR": {
            "layer": "V-PLNT-TREE",
            "color": _ACI_GREEN,
            "description": "Tree",
            "draw_drip_circle": True,
        },
        "FF": {
            "layer": "V-NODE",
            "color": _ACI_WHITE,
            "description": "Finished floor elevation",
            "label_prefix": "FFE=",
            "label_elevation": True,
        },
        "EL": {
            "layer": "V-UTIL-ELEC",
            "color": _ACI_YELLOW,
            "description": "Electric",
        },
        "GA": {
            "layer": "V-UTIL-GAS",
            "color": _ACI_MAGENTA,
            "description": "Gas",
        },
        "WA": {
            "layer": "V-UTIL-WATR",
            "color": _ACI_BLUE,
            "description": "Water",
        },
        "SE": {
            "layer": "V-UTIL-SEWR",
            "color": _ACI_GREEN,
            "description": "Sewer",
        },
        "CP": {
            "layer": "V-SURV-CTRL",
            "color": _ACI_MAGENTA,
            "description": "Control point",
        },
        "BM": {
            "layer": "V-SURV-CTRL",
            "color": _ACI_MAGENTA,
            "description": "Benchmark",
            "label_elevation": True,
        },
        "EP": {
            "layer": "V-UTIL-ELEC",
            "color": _ACI_YELLOW,
            "description": "Electric pole",
        },
        "CB": {
            "layer": "V-UTIL-SEWR",
            "color": _ACI_GREEN,
            "description": "Catch basin",
        },
        "MH": {
            "layer": "V-UTIL-SEWR",
            "color": _ACI_GREEN,
            "description": "Manhole",
        },
        "EB": {
            "layer": "V-EASEMENT",
            "color": _ACI_YELLOW,
            "description": "Easement boundary",
            "auto_connect": True,
        },
        "SB": {
            "layer": "V-SETBACK",
            "color": _ACI_YELLOW,
            "description": "Setback boundary",
            "auto_connect": True,
        },
    },
}

# Layers defined in default config plus their ACI colors
DEFAULT_LAYERS: Dict[str, int] = {
    "V-NODE": _ACI_WHITE,
    "V-NODE-TEXT": _ACI_WHITE,
    "V-PROP": _ACI_RED,
    "V-TOPO-SPOT": _ACI_CYAN,
    "V-TOPO-MAJR": _ACI_CYAN,    # major contours
    "V-TOPO-MINR": _ACI_CYAN,    # minor contours
    "V-BLDG": _ACI_WHITE,
    "V-EASEMENT": _ACI_YELLOW,   # easement reference lines
    "V-SETBACK": _ACI_YELLOW,    # setback reference lines
    "V-UTIL-ELEC": _ACI_YELLOW,
    "V-UTIL-GAS": _ACI_MAGENTA,
    "V-UTIL-WATR": _ACI_BLUE,
    "V-UTIL-SEWR": _ACI_GREEN,
    "V-PLNT-TREE": _ACI_GREEN,
    "V-SURV-CTRL": _ACI_MAGENTA,
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load and merge a user config file with defaults.

    Args:
        config_path: Path to a YAML or JSON config file. If None, returns defaults.

    Returns:
        Merged configuration dictionary.

    Raises:
        FileNotFoundError: If config_path is specified but does not exist.
        ValueError: If the config file cannot be parsed or contains invalid values.
    """
    config = _deep_copy(DEFAULT_CONFIG)

    if config_path is None:
        return config

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()

    suffix = path.suffix.lower()
    try:
        if suffix in (".yaml", ".yml"):
            user_config = yaml.safe_load(raw) or {}
        elif suffix == ".json":
            user_config = json.loads(raw)
        else:
            # Try YAML first, fall back to JSON
            try:
                user_config = yaml.safe_load(raw) or {}
            except yaml.YAMLError:
                user_config = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"Failed to parse config file {config_path}: {exc}") from exc

    _deep_merge(config, user_config)
    _validate_config(config)

    logger.debug("Loaded config from %s", config_path)
    return config


def get_feature_config(config: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Return the feature config for a given code, falling back to a generic default.

    Args:
        config: Full configuration dictionary.
        code: Feature code string (e.g. "HC", "PC", "GR").

    Returns:
        Feature configuration dict with at least 'layer' and 'color' keys.
    """
    feature_codes = config.get("feature_codes", {})
    if code in feature_codes:
        return feature_codes[code]

    logger.warning("Unknown feature code '%s'; placing on V-NODE layer", code)
    return {"layer": "V-NODE", "color": _ACI_WHITE, "description": f"Unknown code: {code}"}


def collect_layers(config: Dict[str, Any]) -> Dict[str, int]:
    """Build the complete layer→color mapping from config.

    Args:
        config: Full configuration dictionary.

    Returns:
        Dict mapping layer name to ACI color integer.
    """
    layers = dict(DEFAULT_LAYERS)
    for code_cfg in config.get("feature_codes", {}).values():
        layer = code_cfg.get("layer")
        color = code_cfg.get("color", _ACI_WHITE)
        if layer:
            layers.setdefault(layer, color)
    return layers


def _deep_copy(obj: Any) -> Any:
    """Return a deep copy of a plain dict/list/scalar structure."""
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj


def _deep_merge(base: Dict, override: Dict) -> None:
    """Recursively merge override into base in-place."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _validate_config(config: Dict[str, Any]) -> None:
    """Raise ValueError on obviously invalid config entries."""
    method = config.get("localization", {}).get("method", "two_point")
    if method not in ("two_point", "helmert"):
        raise ValueError(
            f"localization.method must be 'two_point' or 'helmert', got '{method}'"
        )

    for name, fc in config.get("feature_codes", {}).items():
        if "layer" not in fc:
            raise ValueError(f"Feature code '{name}' is missing required 'layer' key")
        color = fc.get("color", 7)
        if not isinstance(color, int) or not (1 <= color <= 256):
            raise ValueError(
                f"Feature code '{name}' color must be an integer 1-256, got {color!r}"
            )
