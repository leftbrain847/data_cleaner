"""Inject the faults in config/faults.yml into clean source tables.

Each row gets at most one fault, so the evaluation can say exactly which fault a row came from.
Returns the landing tables (row-numbered) plus a manifest: fault id -> affected row ids.
"""
import random
from datetime import date, timedelta

from .tables import ROW_ID, copy_table, number_rows

FAULT_KEY = "_fault"


def _pick(rng, table, used, rate, where=None):
    pool = [i for i, r in enumerate(table["rows"]) if i not in used
            and all(r.get(k) == v for k, v in (where or {}).items())]
    k = min(len(pool), max(1, round(rate * len(table["rows"]))))
    picked = rng.sample(pool, k)
    used.update(picked)
    return picked


def _mangle(value, rng):
    if value is None:
        return value
    styles = [lambda v: v.lower() + " ", lambda v: " " + v.upper(), lambda v: v.swapcase()]
    return rng.choice(styles)(value)


def inject(source, faults, seed):
    """source: {table_name: table}. Returns (landing, manifest)."""
    rng = random.Random(seed)
    landing = {name: copy_table(t) for name, t in source.items()}
    used = {name: set() for name in landing}
    table_faults = []

    for f in faults:
        if not f.get("enabled", True):
            continue
        name, kind = f["table"], f["kind"]
        t = landing[name]
        col = f.get("column")
        if kind == "drop_rows":
            keep = round(len(t["rows"]) * f["keep"])
            t["rows"] = t["rows"][:keep]
            table_faults.append(f)
            continue
        if kind == "drop_column":
            t["columns"] = [c for c in t["columns"] if c != col]
            for r in t["rows"]:
                r.pop(col, None)
            table_faults.append(f)
            continue

        picked = _pick(rng, t, used[name], f.get("rate", 0.01), f.get("where"))
        for i in picked:
            r = t["rows"][i]
            if kind == "null_out":
                r[col] = None
            elif kind == "bad_value":
                r[col] = rng.choice(f["values"])
            elif kind == "mangle_case":
                r[col] = _mangle(r[col], rng)
            elif kind == "date_format":
                r[col] = date.fromisoformat(r[col]).strftime(f["format"])
            elif kind == "shift_date":
                base = date.fromisoformat(r[f["relative_to"]])
                r[col] = (base + timedelta(days=f["days"])).isoformat()
            elif kind == "duplicate":
                dup = dict(r)
                dup[FAULT_KEY] = f["id"]
                t["rows"].append(dup)
                used[name].add(len(t["rows"]) - 1)   # the copy can't take a second fault
                continue
            else:
                raise ValueError(f"unknown fault kind {kind!r} in {f['id']}")
            r[FAULT_KEY] = f["id"]

    manifest = {}
    for name, t in landing.items():
        number_rows(t)
        for r in t["rows"]:
            fid = r.pop(FAULT_KEY, None)
            if fid:
                manifest.setdefault(fid, []).append(r[ROW_ID])
    for f in table_faults:
        manifest[f["id"]] = []
    return landing, manifest
