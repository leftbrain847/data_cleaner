"""generate -> inject faults -> repair -> check contracts -> split clean / quarantine -> evaluate."""
import json
import subprocess
import sys
from dataclasses import asdict

from .config import load_config
from .contracts import build_checks, load_contracts
from .engine import connect, run_checks
from .faults import inject
from .repairs import apply_repairs
from .tables import ROW_ID, copy_table, number_rows, read_csv, write_csv


def generate(cfg):
    out = cfg["abs"]["source"]
    subprocess.run([sys.executable, str(cfg["root"] / cfg["source"]["generator"]), str(out)],
                   check=True, capture_output=True)
    return {t: number_rows(read_csv(out / f"{t}.csv")) for t in cfg["source"]["tables"]}


def validate(tables, contracts):
    checks = [ch for c in contracts for ch in build_checks(c)]
    contract_columns = {obj.get("physicalName", obj["name"]): [p["name"] for p in obj.get("properties", [])]
                        for c in contracts for obj in c.get("schema", [])}
    con = connect(tables)
    try:
        return checks, run_checks(con, checks, tables, contract_columns)
    finally:
        con.close()


def split(tables, results):
    """Row-level failures go to quarantine with reasons; everything else is clean."""
    reasons = {}
    for res in results:
        if res["level"] == "row":
            for rid in res["rows"]:
                reasons.setdefault((res["table"], rid), []).append(res["id"])
    clean, quarantine = {}, {}
    for name, t in tables.items():
        clean[name] = {"columns": t["columns"], "rows": []}
        quarantine[name] = {"columns": t["columns"], "rows": []}
        for r in t["rows"]:
            why = reasons.get((name, r[ROW_ID]))
            if why:
                quarantine[name]["rows"].append({**r, "_reasons": "; ".join(why)})
            else:
                clean[name]["rows"].append(r)
    return clean, quarantine


def evaluate(faults, manifest, results, repair_log, quarantine, checks):
    """Did every injected fault get the outcome the catalog expects?

    A row flagged without being injected is a false positive, except a cascade: a child row held back only
    because its parent table arrived partial (a table-level fault). Those are expected and counted separately.
    """
    by_fault = {f["id"]: f for f in faults}
    partial = {by_fault[fid]["table"] for fid in manifest if by_fault[fid]["kind"] == "drop_rows"}
    cascade_checks = {c.id for c in checks if c.kind == "references" and c.target in partial}
    reasons = {(n, r[ROW_ID]): set(r["_reasons"].split("; ")) for n, t in quarantine.items() for r in t["rows"]}
    cascaded = {k for k, why in reasons.items() if why <= cascade_checks}
    q_rows = set(reasons) - cascaded          # held back for their own sake
    repaired = {(e["table"], e["row"]) for e in repair_log}
    failed_tables = {r["table"] for r in results if r["level"] == "table" and r["status"] == "fail"}
    rows, injected = [], set()
    for fid, ids in manifest.items():
        f = by_fault[fid]
        t = f["table"]
        injected.update((t, i) for i in ids)
        if f["expect"] == "table":
            got = "table" if t in failed_tables else "missed"
            n, hit = 1, int(got == "table")
        else:
            held = set(reasons) if f["expect"] == "quarantine" else q_rows  # cascade can't excuse a missed repair
            outcomes = ["quarantine" if (t, i) in held else "repair" if (t, i) in repaired else "missed" for i in ids]
            n, hit = len(ids), sum(o == f["expect"] for o in outcomes)
            got = f["expect"] if hit == n else ", ".join(sorted(set(outcomes)))
        rows.append({"fault": fid, "table": t, "kind": f["kind"], "injected": n, "expect": f["expect"],
                     "got": got, "matched": hit, "pass": hit == n})
    false_pos = sorted(k for k in q_rows | repaired if k not in injected)
    return {"faults": rows, "false_positives": [{"table": t, "row": i} for t, i in false_pos],
            "cascade": len(cascaded - injected), "pass": all(r["pass"] for r in rows) and not false_pos}


def run(cfg=None, write=True):
    cfg = cfg or load_config()
    contracts = load_contracts(cfg["root"] / cfg["contracts"]["dir"])
    source = generate(cfg)

    # Baseline: untouched source must pass every contract (no false alarms on good data)
    _, baseline = validate({n: copy_table(t) for n, t in source.items()}, contracts)

    landing, manifest = inject(source, cfg["fault_list"], cfg["faults"]["seed"])
    if write:
        for n, t in landing.items():
            write_csv(cfg["abs"]["landing"] / f"{n}.csv", t)
    repair_log = apply_repairs(landing, contracts, cfg["repair_list"])
    checks, results = validate(landing, contracts)
    clean, quarantine = split(landing, results)
    ev = evaluate(cfg["fault_list"], manifest, results, repair_log, quarantine, checks)

    summary = {
        "rows_in": sum(len(t["rows"]) for t in landing.values()),
        "rows_clean": sum(len(t["rows"]) for t in clean.values()),
        "rows_repaired": len({(e["table"], e["row"]) for e in repair_log}),
        "rows_quarantined": sum(len(t["rows"]) for t in quarantine.values()),
        "checks": len(results),
        "checks_failed": sum(r["status"] == "fail" for r in results),
        "baseline_failures": [r["id"] for r in baseline if r["status"] not in ("pass",)],
        "faults_on": len(manifest),
    }
    out = {"summary": summary, "results": results, "baseline": baseline, "eval": ev, "repairs": repair_log,
           "manifest": manifest, "checks": [asdict(c) for c in checks],
           "contract_columns": {t: cols for t, cols in _contract_columns(contracts).items()},
           "tables": {"landing": landing, "quarantine": quarantine, "clean": clean, "source": source}}
    if write:
        for n in landing:
            write_csv(cfg["abs"]["clean"] / f"{n}.csv", clean[n])
            write_csv(cfg["abs"]["quarantine"] / f"{n}.csv", quarantine[n], extra_columns=["_row_id", "_reasons"])
        cfg["abs"]["work"].mkdir(parents=True, exist_ok=True)
        slim = {k: v for k, v in out.items() if k != "tables"}
        (cfg["abs"]["work"] / "results.json").write_text(json.dumps(slim, indent=1, default=str))
    return out


def _contract_columns(contracts):
    return {obj.get("physicalName", obj["name"]): [p["name"] for p in obj.get("properties", [])]
            for c in contracts for obj in c.get("schema", [])}
