"""Tables travel through the pipeline as plain Python: {"columns": [...], "rows": [dict, ...]}.

Each row carries a hidden "_row_id" (its position in the landing file) so checks, repairs and the
fault manifest all point at the same row.
"""
import csv
from pathlib import Path

ROW_ID = "_row_id"


def read_csv(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = [{k: (v if v != "" else None) for k, v in r.items()} for r in reader]
        return {"columns": list(reader.fieldnames or []), "rows": rows}


def number_rows(table):
    for i, r in enumerate(table["rows"], start=1):
        r[ROW_ID] = i
    return table


def write_csv(path, table, extra_columns=()):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(table["columns"]) + list(extra_columns)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in table["rows"]:
            w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])


def copy_table(table):
    return {"columns": list(table["columns"]), "rows": [dict(r) for r in table["rows"]]}
