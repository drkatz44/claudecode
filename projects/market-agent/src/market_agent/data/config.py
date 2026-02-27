"""Configuration management for market-agent.

Config file: ~/.market-agent/config.yaml
"""

import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, field_validator

CONFIG_DIR = Path.home() / ".market-agent"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

# Allowed strategy names
VALID_STRATEGIES = {"momentum", "volatility", "reversion", "all"}
# Symbol pattern: 1-10 alphanumeric + optional hyphen (for BTC-USD etc)
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9\-]{1,10}$")


class ScanConfig(BaseModel):
    """Scan configuration."""
    symbols: list[str] = []
    strategies: list[str] = ["momentum", "volatility"]
    min_confidence: float = 0.5

    @field_validator("strategies")
    @classmethod
    def validate_strategies(cls, v):
        for s in v:
            if s not in VALID_STRATEGIES:
                raise ValueError(f"Unknown strategy: {s}. Valid: {VALID_STRATEGIES}")
        return v

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v):
        validated = []
        for s in v:
            s = s.upper().strip()
            if SYMBOL_PATTERN.match(s):
                validated.append(s)
        return validated

    @field_validator("min_confidence")
    @classmethod
    def validate_confidence(cls, v):
        return max(0.0, min(1.0, v))


class DataSourcesConfig(BaseModel):
    """Toggle external data sources on/off."""
    cot: bool = True
    comex: bool = True
    usgs: bool = False


class MarketAgentConfig(BaseModel):
    """Top-level configuration."""
    scan: ScanConfig = ScanConfig()
    reports_dir: str = str(Path.home() / ".market-agent" / "reports")
    data_sources: DataSourcesConfig = DataSourcesConfig()


def load_config() -> MarketAgentConfig:
    """Load config from YAML file. Returns defaults if file doesn't exist."""
    if not CONFIG_PATH.exists():
        return MarketAgentConfig()

    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            return MarketAgentConfig()
        return MarketAgentConfig(**data)
    except (yaml.YAMLError, ValueError, TypeError):
        return MarketAgentConfig()


def save_default_config() -> Path:
    """Create config.yaml with defaults if missing. Returns path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        return CONFIG_PATH

    config = MarketAgentConfig()
    data = {
        "scan": {
            "symbols": [],
            "strategies": config.scan.strategies,
            "min_confidence": config.scan.min_confidence,
        },
        "reports_dir": config.reports_dir,
        "data_sources": {
            "cot": config.data_sources.cot,
            "comex": config.data_sources.comex,
            "usgs": config.data_sources.usgs,
        },
    }

    CONFIG_PATH.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")
    CONFIG_PATH.chmod(0o600)
    return CONFIG_PATH
