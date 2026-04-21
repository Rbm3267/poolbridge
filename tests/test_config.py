"""Tests for config loading, merging, and validation."""

import json
import os
import tempfile

import pytest
import yaml

from poolbridge.config import (
    DEFAULT_CONFIG,
    collect_layers,
    get_feature_config,
    load_config,
)


class TestLoadConfig:
    def test_returns_defaults_when_no_path(self):
        cfg = load_config()
        assert "feature_codes" in cfg
        assert "HC" in cfg["feature_codes"]
        assert cfg["units"]["convert_to_feet"] is True

    def test_load_yaml(self, tmp_path):
        data = {"units": {"convert_to_feet": False}}
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(data))
        cfg = load_config(str(p))
        assert cfg["units"]["convert_to_feet"] is False

    def test_load_json(self, tmp_path):
        data = {"output": {"pdmode": 3}}
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(data))
        cfg = load_config(str(p))
        assert cfg["output"]["pdmode"] == 3

    def test_user_feature_codes_merged_with_defaults(self, tmp_path):
        data = {
            "feature_codes": {
                "POOL": {"layer": "V-POOL", "color": 4, "description": "Pool edge"}
            }
        }
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(data))
        cfg = load_config(str(p))
        # Custom code added
        assert "POOL" in cfg["feature_codes"]
        # Built-in codes still present
        assert "HC" in cfg["feature_codes"]

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_raises_value_error_on_invalid_method(self, tmp_path):
        data = {"localization": {"method": "invalid_method"}}
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(data))
        with pytest.raises(ValueError, match="method"):
            load_config(str(p))

    def test_raises_value_error_on_missing_layer(self, tmp_path):
        data = {"feature_codes": {"XX": {"color": 1}}}
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(data))
        with pytest.raises(ValueError, match="layer"):
            load_config(str(p))

    def test_raises_value_error_on_bad_color(self, tmp_path):
        data = {"feature_codes": {"XX": {"layer": "V-NODE", "color": 999}}}
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(data))
        with pytest.raises(ValueError, match="color"):
            load_config(str(p))

    def test_default_config_is_not_mutated(self):
        cfg1 = load_config()
        cfg1["units"]["convert_to_feet"] = False
        cfg2 = load_config()
        assert cfg2["units"]["convert_to_feet"] is True


class TestGetFeatureConfig:
    def test_known_code_returns_config(self):
        cfg = load_config()
        fc = get_feature_config(cfg, "HC")
        assert fc["layer"] == "V-BLDG"
        assert fc["color"] == 7

    def test_unknown_code_returns_v_node(self):
        cfg = load_config()
        fc = get_feature_config(cfg, "ZZUNK")
        assert fc["layer"] == "V-NODE"

    def test_gr_has_label_elevation(self):
        cfg = load_config()
        fc = get_feature_config(cfg, "GR")
        assert fc.get("label_elevation") is True

    def test_tr_has_drip_circle(self):
        cfg = load_config()
        fc = get_feature_config(cfg, "TR")
        assert fc.get("draw_drip_circle") is True

    def test_ff_has_label_prefix(self):
        cfg = load_config()
        fc = get_feature_config(cfg, "FF")
        assert fc.get("label_prefix") == "FFE="


class TestCollectLayers:
    def test_all_default_layers_present(self):
        cfg = load_config()
        layers = collect_layers(cfg)
        expected = [
            "V-NODE", "V-NODE-TEXT", "V-PROP", "V-TOPO-SPOT", "V-BLDG",
            "V-UTIL-ELEC", "V-UTIL-GAS", "V-UTIL-WATR", "V-UTIL-SEWR",
            "V-PLNT-TREE", "V-SURV-CTRL",
        ]
        for layer in expected:
            assert layer in layers, f"Missing expected layer: {layer}"

    def test_custom_layer_added(self, tmp_path):
        data = {"feature_codes": {"PL": {"layer": "V-POOL-EDGE", "color": 4}}}
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(data))
        cfg = load_config(str(p))
        layers = collect_layers(cfg)
        assert "V-POOL-EDGE" in layers
