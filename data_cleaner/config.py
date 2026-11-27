"""Load settings. Everything tunable lives in config/*.yml, not in code."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "pipeline.yml"


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_config(path=DEFAULT_CONFIG, root=ROOT, overrides=None):
    """Return the pipeline config with absolute paths and the fault/repair catalogs attached.

    overrides: dict merged on top (one level deep per section), handy for tests and one-off runs.
    """
    cfg = load_yaml(path)
    for section, values in (overrides or {}).items():
        if isinstance(values, dict) and isinstance(cfg.get(section), dict):
            cfg[section] = {**cfg[section], **values}
        else:
            cfg[section] = values
    root = Path(root)
    cfg["root"] = root
    cfg["abs"] = {k: root / v for k, v in cfg["paths"].items()}
    if "fault_list" not in cfg:
        cfg["fault_list"] = load_yaml(root / cfg["faults"]["catalog"])["faults"]
    if "repair_list" not in cfg:
        cfg["repair_list"] = load_yaml(root / cfg["repairs"]["catalog"])["repairs"]
    return cfg
