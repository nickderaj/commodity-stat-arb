from pathlib import Path
import yaml
from config.schema import SpreadDefinition


_CONFIG_DIR = Path(__file__).parent


def load_spread(path: Path) -> SpreadDefinition:
    with open(path) as f:
        data = yaml.safe_load(f)
    return SpreadDefinition(**data)


def load_all_spreads(config_dir: Path = _CONFIG_DIR) -> list[SpreadDefinition]:
    paths = sorted(config_dir.glob("*.yaml"))
    return [load_spread(p) for p in paths]
