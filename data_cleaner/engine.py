"""Run checks in DuckDB. The same SQL runs in the browser (DuckDB-WASM) for uploaded files."""
import duckdb

from .contracts import q
from .tables import ROW_ID


def connect(tables):
    """tables: {name: table}. Every column lands as VARCHAR, like a raw landing zone."""
    con = duckdb.connect()
    for name, t in tables.items():
        cols = [c for c in t["columns"]]
        ddl = ", ".join([f"{ROW_ID} BIGINT"] + [f"{q(c)} VARCHAR" for c in cols])
        con.execute(f"CREATE TABLE {q(name)} ({ddl})")
        if t["rows"]:
            ph = ", ".join(["?"] * (len(cols) + 1))
            con.executemany(f"INSERT INTO {q(name)} VALUES ({ph})",
                            [[r[ROW_ID]] + [r.get(c) for c in cols] for r in t["rows"]])
    return con


def run_checks(con, checks, tables, contract_columns):
    """Returns one result per check: status pass | fail | skipped | error, and failing row ids."""
    results = []
    for ch in checks:
        res = {"id": ch.id, "contract": ch.contract, "table": ch.table, "level": ch.level, "kind": ch.kind,
               "column": ch.column, "description": ch.description, "rows": [], "status": "pass"}
        present = set(tables[ch.table]["columns"]) if ch.table in tables else set()
        if ch.table not in tables:
            res.update(status="fail", detail="table did not arrive")
        elif ch.kind == "schema":
            missing = [c for c in contract_columns[ch.table] if c not in present]
            if missing:
                res.update(status="fail", detail="missing: " + ", ".join(missing))
        elif any(c not in present for c in ch.needs):
            res.update(status="skipped", detail="column missing (see schema check)")
        else:
            try:
                if ch.level == "row":
                    res["rows"] = sorted(r[0] for r in con.execute(ch.sql).fetchall())
                    res["status"] = "fail" if res["rows"] else "pass"
                else:
                    ok = con.execute(ch.sql).fetchone()[0]
                    res["status"] = "pass" if ok else "fail"
            except duckdb.Error as e:
                res.update(status="error", detail=str(e).splitlines()[0])
        results.append(res)
    return results
