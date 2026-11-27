"""Turn ODCS contracts into checks.

Supported subset (everything else in a contract is carried along but not executed):
  property: required, unique, logicalType (integer | number | date | string),
            logicalTypeOptions (minimum, maximum, pattern), relationships[].to,
            quality[] metric invalidValues with arguments.validValues
  object:   every property present (schema), quality[] metric rowCount (mustBeBetween),
            quality[] type sql with mustBe: 0

A row check's SQL returns the _row_id of every failing row. A table check's SQL returns one boolean: passed.
Column names are quoted; values are passed through _lit, which escapes quotes.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re

from .config import load_yaml

CASTS = {"integer": "BIGINT", "number": "DOUBLE", "date": "DATE"}
ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"
COUNT_PREFIX = re.compile(r"^\s*SELECT\s+COUNT\(\*\)\s+FROM\s+", re.I)


@dataclass
class Check:
    id: str
    contract: str
    table: str
    level: str            # "row" | "table"
    kind: str
    sql: str
    column: str | None = None
    needs: list = field(default_factory=list)   # columns that must exist for the check to run
    description: str = ""
    target: str | None = None                   # references: the parent table


def q(name):
    return '"' + name.replace('"', '""') + '"'


def _lit(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def load_contracts(contract_dir):
    return [load_yaml(p) for p in sorted(Path(contract_dir).glob("*.odcs.yaml"))]


def valid_values(contract):
    """{(table, column): [valid values]} from invalidValues rules; repairs use it too."""
    out = {}
    for obj in contract.get("schema", []):
        for p in obj.get("properties", []):
            for rule in p.get("quality", []) or []:
                if rule.get("metric") == "invalidValues":
                    out[(obj["name"], p["name"])] = [str(v) for v in rule["arguments"]["validValues"]]
    return out


def typed_columns(contract):
    return {(obj["name"], p["name"]): p.get("logicalType", "string")
            for obj in contract.get("schema", []) for p in obj.get("properties", [])}


def build_checks(contract):
    cid = contract["id"]
    checks = []
    for obj in contract.get("schema", []):
        t = obj.get("physicalName", obj["name"])
        cols = [p["name"] for p in obj.get("properties", [])]
        checks.append(Check(f"{t}.schema", cid, t, "table", "schema", "", needs=cols,
                            description="All expected columns showed up: " + ", ".join(cols)))
        for p in obj.get("properties", []):
            c, qc = p["name"], q(p["name"])
            base = f"SELECT _row_id FROM {q(t)} WHERE "
            mk = lambda kind, where, desc: Check(f"{t}.{c}.{kind}", cid, t, "row", kind, base + where, c, [c], desc)
            if p.get("required"):
                checks.append(mk("required", f"{qc} IS NULL", f"{c} is blank"))
            if p.get("unique"):
                checks.append(Check(
                    f"{t}.{c}.unique", cid, t, "row", "unique",
                    f"SELECT _row_id FROM (SELECT _row_id, row_number() OVER (PARTITION BY {qc} ORDER BY _row_id) AS n "
                    f"FROM {q(t)} WHERE {qc} IS NOT NULL) WHERE n > 1", c, [c], f"Same {c} sent more than once (first copy kept)"))
            lt = p.get("logicalType", "string")
            if lt in CASTS:
                cond = f"{qc} IS NOT NULL AND TRY_CAST({qc} AS {CASTS[lt]}) IS NULL"
                if lt == "date":
                    cond = f"{qc} IS NOT NULL AND (NOT regexp_matches({qc}, '{ISO_DATE}') OR TRY_CAST({qc} AS DATE) IS NULL)"
                checks.append(mk("type", cond, f"{c} isn't a valid {lt}"))
            opts = p.get("logicalTypeOptions") or {}
            cast = CASTS.get(lt)
            for key, op in (("minimum", "<"), ("maximum", ">")):
                if key in opts and cast:
                    v = f"CAST({_lit(opts[key])} AS {cast})"
                    checks.append(mk(key, f"TRY_CAST({qc} AS {cast}) {op} {v}", f"{c} is {'below' if op == '<' else 'above'} {opts[key]}"))
            if "pattern" in opts:
                checks.append(mk("pattern", f"{qc} IS NOT NULL AND NOT regexp_matches({qc}, {_lit(opts['pattern'])})",
                                 f"{c} isn't in the expected format"))
            for rel in p.get("relationships", []) or []:
                pt, pc = rel["to"].split(".")
                checks.append(Check(
                    f"{t}.{c}.references", cid, t, "row", "references",
                    base + f"{qc} IS NOT NULL AND {qc} NOT IN (SELECT {q(pc)} FROM {q(pt)} WHERE {q(pc)} IS NOT NULL)",
                    c, [c], f"{c} doesn't match any {rel['to'].split('.')[0]} record", target=pt))
            for rule in p.get("quality", []) or []:
                if rule.get("metric") == "invalidValues":
                    vals = ", ".join(_lit(str(v)) for v in rule["arguments"]["validValues"])
                    checks.append(mk("valid_values", f"{qc} IS NOT NULL AND {qc} NOT IN ({vals})",
                                     f"{c} isn't one of: " + ", ".join(map(str, rule['arguments']['validValues']))))
        for i, rule in enumerate(obj.get("quality", []) or []):
            rid = rule.get("id", f"rule_{i}")
            if rule.get("metric") == "rowCount":
                lo, hi = rule["mustBeBetween"]
                checks.append(Check(f"{t}.{rid}", cid, t, "table", "row_count",
                                    f"SELECT COUNT(*) BETWEEN {int(lo)} AND {int(hi)} FROM {q(t)}",
                                    description=f"Table should have {lo:,} to {hi:,} rows"))
            elif rule.get("type") == "sql":
                query = " ".join(rule["query"].split())
                needs = [c for c in cols if re.search(rf"\b{re.escape(c)}\b", query)]
                if COUNT_PREFIX.match(query) and rule.get("mustBe", 0) == 0:
                    checks.append(Check(f"{t}.{rid}", cid, t, "row", "sql", COUNT_PREFIX.sub("SELECT _row_id FROM ", query),
                                        needs=needs, description=rule.get("description", query)))
                else:
                    checks.append(Check(f"{t}.{rid}", cid, t, "table", "sql",
                                        f"SELECT ({query}) = {_lit(rule.get('mustBe', 0))}",
                                        needs=needs, description=rule.get("description", query)))
    return checks
