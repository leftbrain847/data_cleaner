"""Safe repairs: fixes that can't change a value's meaning. Logged row by row."""
from datetime import datetime

from .contracts import valid_values, typed_columns
from .tables import ROW_ID


def apply_repairs(tables, contracts, repairs):
    log = []
    enums, dates = {}, set()
    for c in contracts:
        enums.update(valid_values(c))
        dates.update(k for k, v in typed_columns(c).items() if v == "date")
    for rep in repairs:
        if not rep.get("enabled", True):
            continue
        if rep["kind"] == "canonical_enum":
            for (t, col), vals in enums.items():
                lookup = {v.lower(): v for v in vals}
                for r in tables.get(t, {}).get("rows", []):
                    v = r.get(col)
                    if v is not None and v not in vals and v.strip().lower() in lookup:
                        log.append(_entry(rep, t, col, r, v, lookup[v.strip().lower()]))
                        r[col] = lookup[v.strip().lower()]
        elif rep["kind"] == "date_formats":
            for t, col in dates:
                for r in tables.get(t, {}).get("rows", []):
                    v = r.get(col)
                    if v is None or _is_iso(v):
                        continue
                    for fmt in rep["formats"]:
                        try:
                            fixed = datetime.strptime(v.strip(), fmt).date().isoformat()
                        except ValueError:
                            continue
                        log.append(_entry(rep, t, col, r, v, fixed))
                        r[col] = fixed
                        break
        else:
            raise ValueError(f"unknown repair kind {rep['kind']!r}")
    return log


def _is_iso(v):
    try:
        return datetime.strptime(v, "%Y-%m-%d").date().isoformat() == v
    except ValueError:
        return False


def _entry(rep, table, col, row, before, after):
    return {"repair": rep["id"], "table": table, "column": col, "row": row[ROW_ID], "from": before, "to": after}
