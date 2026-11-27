"""python -m data_cleaner [--config config/pipeline.yml]  -> out/ (data) and site/ (report)."""
import argparse
import json
import shutil
import sys

from .config import DEFAULT_CONFIG, load_config
from .pipeline import run
from .report import render


def build(cfg):
    out = run(cfg)
    site = cfg["abs"]["site"]
    (site / "samples").mkdir(parents=True, exist_ok=True)
    (site / "index.html").write_text(render(out, cfg))
    shutil.copy(cfg["abs"]["landing"] / "FactCardiacEvents.csv", site / "samples" / "FactCardiacEvents_landing.csv")
    shutil.copy(cfg["abs"]["source"] / "FactCardiacEvents.csv", site / "samples" / "FactCardiacEvents_clean.csv")
    shutil.copy(cfg["abs"]["work"] / "results.json", site / "results.json")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="data_cleaner")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = ap.parse_args(argv)
    out = build(load_config(args.config))
    s, ev = out["summary"], out["eval"]
    print(json.dumps(s, indent=1))
    print(f"eval: {'PASS' if ev['pass'] else 'FAIL'} ({sum(f['pass'] for f in ev['faults'])}/{len(ev['faults'])} faults, "
          f"{len(ev['false_positives'])} false positives)")
    return 0 if ev["pass"] and not s["baseline_failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
