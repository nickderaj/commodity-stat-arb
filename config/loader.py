"""Loaders for SpreadDefinition YAML configs.

Config files live in config/*.yaml. Each file defines one spread. The loader
validates the YAML against the SpreadDefinition Pydantic model so invalid configs
fail loudly at load time, not mid-backtest.
"""

from pathlib import Path

import yaml

from config.schema import SpreadDefinition

_CONFIG_DIR = Path(__file__).parent


def load_spread(path: Path) -> SpreadDefinition:
    """Load and validate a single SpreadDefinition from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return SpreadDefinition(**data)


def load_all_spreads(config_dir: Path = _CONFIG_DIR) -> list[SpreadDefinition]:
    """Load all *.yaml configs from config_dir and return validated SpreadDefinitions."""
    paths = sorted(config_dir.glob("*.yaml"))
    return [load_spread(p) for p in paths]
