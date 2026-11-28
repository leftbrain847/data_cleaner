"""End-to-end and unit tests. CI runs: pytest -q"""
import copy
import json

import pytest

from data_cleaner.__main__ import build
from data_cleaner.config import load_config
from data_cleaner.contracts import _lit, build_checks, load_contracts
from data_cleaner.engine import connect, run_checks
from data_cleaner.faults import inject
from data_cleaner.pipeline import generate, run
from data_cleaner.repairs import apply_repairs
from data_cleaner.tables import number_rows

PATHS = ["work", "source", "landing", "clean", "quarantine", "site"]


def tmp_cfg(tmp_path):
    return load_config(overrides={"paths": {k: str(tmp_path / k) for k in PATHS}})


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    cfg = tmp_cfg(tmp_path_factory.mktemp("run"))
    return cfg, build(cfg)


def table(cols, rows):
    return number_rows({"columns": cols, "rows": [dict(zip(cols, r)) for r in rows]})


def contract(props, quality=()):
    return {"id": "c", "schema": [{"name": "T", "properties": props, "quality": list(quality)}]}


def check(contract_, tables):
    checks = build_checks(contract_)
    cols = {"T": [p["name"] for p in contract_["schema"][0]["properties"]]}
    return {r["id"]: r for r in run_checks(connect(tables), checks, tables, cols)}


# --- end to end ---------------------------------------------------------------------------------

def test_default_run_passes_its_own_evaluation(default_run):
    _, out = default_run
    ev = out["eval"]
    assert ev["pass"], [f for f in ev["faults"] if not f["pass"]]
    assert len(ev["faults"]) == sum(f["enabled"] for f in load_config()["fault_list"])


def test_clean_source_passes_every_contract(default_run):
    _, out = default_run
    assert out["summary"]["baseline_failures"] == []


def test_no_row_lost(default_run):
    _, out = default_run
    t = out["tables"]
    for name in t["landing"]:
        assert len(t["clean"][name]["rows"]) + len(t["quarantine"][name]["rows"]) == len(t["landing"][name]["rows"])


def test_quarantined_rows_carry_reasons(default_run):
    _, out = default_run
    rows = out["tables"]["quarantine"]["FactCardiacEvents"]["rows"]
    assert rows and all(r["_reasons"] for r in rows)


def test_outputs_written(default_run):
    cfg, _ = default_run
    site = cfg["abs"]["site"]
    html = (site / "index.html").read_text()
    assert html.startswith("<!doctype html>") and "<head>" in html
    assert "fonts.googleapis" not in html and "@import" not in html      # system fonts only
    assert "cdn.jsdelivr" not in html and "unpkg" not in html            # checker served from this site
    csp = html.split('http-equiv="Content-Security-Policy" content="', 1)[1].split('"', 1)[0]
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp and "unsafe-eval'" not in csp.replace("wasm-unsafe-eval", "")
    assert json.loads((site / "results.json").read_text())["eval"]["pass"]
    for t in ["FactCardiacEvents", "DimClinician", "DimLocation"]:
        assert (cfg["abs"]["quarantine"] / f"{t}.csv").exists()
        assert (cfg["abs"]["clean"] / f"{t}.csv").exists()
    assert (site / "samples" / "FactCardiacEvents_landing.csv").exists()


def test_report_escapes_injected_values(tmp_path):
    cfg = tmp_cfg(tmp_path)
    cfg["fault_list"].append({"id": "html_in_data", "enabled": True, "table": "FactCardiacEvents",
                              "kind": "bad_value", "column": "AdmissionStatus",
                              "values": ["<script>alert(1)</script>"], "rate": 0.01, "expect": "quarantine"})
    build(cfg)
    html = (cfg["abs"]["site"] / "index.html").read_text()
    assert "<script>alert(1)</script>" not in html


def test_every_fault_lands_where_expected(tmp_path):
    cfg = tmp_cfg(tmp_path)
    for f in cfg["fault_list"]:
        f["enabled"] = True
    ev = run(cfg, write=False)["eval"]
    assert ev["pass"], ([f for f in ev["faults"] if not f["pass"]], ev["false_positives"][:5])
    assert ev["cascade"] > 0   # a partial clinician load orphans intake rows; expected, not a false alarm


def test_no_faults_means_nothing_held_back(tmp_path):
    cfg = tmp_cfg(tmp_path)
    for f in cfg["fault_list"]:
        f["enabled"] = False
    out = run(cfg, write=False)
    assert out["summary"]["rows_quarantined"] == 0 and out["repairs"] == []


def test_injection_is_deterministic_and_one_fault_per_row(default_run):
    cfg, _ = default_run
    src = generate(cfg)
    a = inject(copy.deepcopy(src), cfg["fault_list"], 27)[1]
    b = inject(copy.deepcopy(src), cfg["fault_list"], 27)[1]
    c = inject(copy.deepcopy(src), cfg["fault_list"], 28)[1]
    assert a == b and a != c
    ids = [i for rows in a.values() for i in rows]
    assert len(ids) == len(set(ids))


# --- units --------------------------------------------------------------------------------------

ENUM = {"name": "s", "logicalType": "string",
        "quality": [{"metric": "invalidValues", "arguments": {"validValues": ["Admitted", "Discharged"]}, "mustBe": 0}]}


def test_enum_repair_only_fixes_case_and_spaces():
    t = {"T": table(["s"], [[" admitted"], ["Unknown"], ["DISCHARGED "]])}
    log = apply_repairs(t, [contract([ENUM])], [{"id": "e", "kind": "canonical_enum"}])
    assert [r["s"] for r in t["T"]["rows"]] == ["Admitted", "Unknown", "Discharged"]
    assert len(log) == 2


def test_date_repair_only_known_formats():
    t = {"T": table(["d"], [["08/03/2024"], ["2024-08-03"], ["N/A"]])}
    apply_repairs(t, [contract([{"name": "d", "logicalType": "date"}])],
                  [{"id": "d", "kind": "date_formats", "formats": ["%m/%d/%Y"]}])
    assert [r["d"] for r in t["T"]["rows"]] == ["2024-08-03", "2024-08-03", "N/A"]


def test_property_checks_flag_the_right_rows():
    props = [{"name": "id", "logicalType": "integer", "required": True, "unique": True},
             {"name": "p", "logicalType": "number", "logicalTypeOptions": {"minimum": 0, "maximum": 1}},
             {"name": "d", "logicalType": "date"}, ENUM]
    t = {"T": table(["id", "p", "d", "s"], [
        ["1", "0.5", "2024-01-01", "Admitted"],
        ["1", "1.5", "2024-13-45", "Nope"],
        [None, "x", "01/02/2024", None]])}
    r = check(contract(props), t)
    assert r["T.id.unique"]["rows"] == [2] and r["T.id.required"]["rows"] == [3]
    assert r["T.p.maximum"]["rows"] == [2] and r["T.p.type"]["rows"] == [3]
    assert r["T.d.type"]["rows"] == [2, 3] and r["T.s.valid_values"]["rows"] == [2]
    assert r["T.schema"]["status"] == "pass"


def test_missing_column_fails_schema_and_skips_dependent_checks():
    props = [{"name": "a", "required": True}, {"name": "b", "required": True}]
    r = check(contract(props), {"T": table(["a"], [["x"]])})
    assert r["T.schema"]["status"] == "fail" and "b" in r["T.schema"]["detail"]
    assert r["T.b.required"]["status"] == "skipped"


def test_sql_rule_becomes_row_check():
    c = contract([{"name": "a"}], [{"id": "r", "type": "sql", "query": "SELECT COUNT(*) FROM T WHERE a = 'bad'", "mustBe": 0}])
    chk = [x for x in build_checks(c) if x.kind == "sql"][0]
    assert chk.level == "row" and chk.sql.startswith("SELECT _row_id FROM ")
    assert check(c, {"T": table(["a"], [["ok"], ["bad"]])})["T.r"]["rows"] == [2]


def test_hostile_names_and_values_are_quoted():
    assert _lit("O'Brien") == "'O''Brien'" and _lit(3) == "3"
    props = [{"name": 'we"ird; DROP', "required": True}]
    r = check(contract(props), {"T": table(['we"ird; DROP'], [["x"], [None]])})
    assert r['T.we"ird; DROP.required']["rows"] == [2]


def test_contracts_are_odcs_shaped_and_hold_no_connection_details():
    cfg = load_config()
    for c in load_contracts(cfg["root"] / cfg["contracts"]["dir"]):
        assert c["kind"] == "DataContract" and c["apiVersion"].startswith("v3")
        assert {s["type"] for s in c["servers"]} >= {"duckdb", "sqlserver"}
        for s in c["servers"]:
            for k in ("host", "database"):
                assert k not in s or "${" in str(s[k])


def test_csp_hash_matches_the_inline_script(default_run):
    import base64, hashlib, re
    cfg, _ = default_run
    html = (cfg["abs"]["site"] / "index.html").read_text()
    js = re.findall(r'<script type="module">(.*?)</script>', html, re.S)
    assert len(js) == 1
    h = base64.b64encode(hashlib.sha256(js[0].encode()).digest()).decode()
    assert f"'sha256-{h}'" in html


def test_upload_banner_warns_against_real_data(default_run):
    cfg, _ = default_run
    assert "Don't upload real patient or work data" in (cfg["abs"]["site"] / "index.html").read_text()
