"""Tests for configuration management."""

from pathlib import Path

import pytest
import yaml

from market_agent.data.config import (
    MarketAgentConfig,
    ScanConfig,
    load_config,
    save_default_config,
)


class TestScanConfig:
    def test_defaults(self):
        cfg = ScanConfig()
        assert cfg.strategies == ["momentum", "volatility"]
        assert cfg.min_confidence == 0.5
        assert cfg.symbols == []

    def test_validates_strategies(self):
        cfg = ScanConfig(strategies=["momentum", "all"])
        assert cfg.strategies == ["momentum", "all"]

    def test_rejects_invalid_strategy(self):
        with pytest.raises(ValueError, match="Unknown strategy"):
            ScanConfig(strategies=["fake_strategy"])

    def test_validates_symbols(self):
        cfg = ScanConfig(symbols=["aapl", "MSFT", "BTC-USD"])
        assert cfg.symbols == ["AAPL", "MSFT", "BTC-USD"]

    def test_strips_invalid_symbols(self):
        cfg = ScanConfig(symbols=["AAPL", "invalid symbol!", "TOOLONGSYMBOLNAME"])
        assert cfg.symbols == ["AAPL"]

    def test_clamps_confidence(self):
        cfg = ScanConfig(min_confidence=2.0)
        assert cfg.min_confidence == 1.0

        cfg = ScanConfig(min_confidence=-0.5)
        assert cfg.min_confidence == 0.0


class TestMarketAgentConfig:
    def test_defaults(self):
        cfg = MarketAgentConfig()
        assert isinstance(cfg.scan, ScanConfig)
        assert "reports" in cfg.reports_dir


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path, monkeypatch):
        import market_agent.data.config as cfg_mod
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "nonexistent.yaml")
        cfg = load_config()
        assert isinstance(cfg, MarketAgentConfig)
        assert cfg.scan.strategies == ["momentum", "volatility"]

    def test_loads_valid_yaml(self, tmp_path, monkeypatch):
        import market_agent.data.config as cfg_mod
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({
            "scan": {
                "symbols": ["AAPL", "NVDA"],
                "strategies": ["momentum"],
                "min_confidence": 0.7,
            }
        }))
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_path)
        cfg = load_config()
        assert cfg.scan.symbols == ["AAPL", "NVDA"]
        assert cfg.scan.strategies == ["momentum"]
        assert cfg.scan.min_confidence == 0.7

    def test_invalid_yaml_returns_defaults(self, tmp_path, monkeypatch):
        import market_agent.data.config as cfg_mod
        config_path = tmp_path / "config.yaml"
        config_path.write_text(":::invalid yaml{{{}}")
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_path)
        cfg = load_config()
        assert isinstance(cfg, MarketAgentConfig)

    def test_non_dict_yaml_returns_defaults(self, tmp_path, monkeypatch):
        import market_agent.data.config as cfg_mod
        config_path = tmp_path / "config.yaml"
        config_path.write_text("just a string")
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_path)
        cfg = load_config()
        assert isinstance(cfg, MarketAgentConfig)


class TestSaveDefaultConfig:
    def test_creates_file(self, tmp_path, monkeypatch):
        import market_agent.data.config as cfg_mod
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_path)

        path = save_default_config()
        assert path.exists()
        data = yaml.safe_load(path.read_text())
        assert "scan" in data
        assert "strategies" in data["scan"]

    def test_does_not_overwrite(self, tmp_path, monkeypatch):
        import market_agent.data.config as cfg_mod
        config_path = tmp_path / "config.yaml"
        config_path.write_text("custom: true")
        monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_path)

        save_default_config()
        assert "custom: true" in config_path.read_text()

    def test_roundtrip(self, tmp_path, monkeypatch):
        import market_agent.data.config as cfg_mod
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_path)

        save_default_config()
        cfg = load_config()
        assert cfg.scan.strategies == ["momentum", "volatility"]
