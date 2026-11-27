"""Render the phone-first report: one self-contained HTML file (inline CSS/JS, system fonts).

The "Check your own CSV" section runs the same contract SQL in the visitor's browser with DuckDB-WASM.
Files are read locally and never uploaded anywhere.
"""
import json
from html import escape

from .tables import ROW_ID

DUCKDB_WASM = "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.32.0/+esm"  # pinned; same as portfolio
MAX_UPLOAD_MB = 25

CSS = """
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--text:#e7e9ee;--muted:#9aa3b2;--good:#3fb27f;--bad:#e5534b;--warn:#d29922;--accent:#58a6ff}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:760px;margin:0 auto;padding:20px 14px 60px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px}p{margin:6px 0}
.muted{color:var(--muted)}.small{font-size:13px}
code{overflow-wrap:anywhere;font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--panel);padding:1px 4px;border-radius:4px}
.pill{display:inline-block;padding:4px 10px;border-radius:999px;font-weight:600;font-size:13px;margin-top:10px}
.pill.ok{background:rgba(63,178,127,.15);color:var(--good)}.pill.no{background:rgba(229,83,75,.15);color:var(--bad)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:8px;margin-top:16px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px}
.tile b{display:block;font-size:22px;font-variant-numeric:tabular-nums}.tile span{color:var(--muted);font-size:12px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{color:var(--muted);font-weight:600;background:var(--panel)}tr:last-child td{border-bottom:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:var(--good)}.no{color:var(--bad)}.skip{color:var(--warn)}
details{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin:8px 0;padding:0 12px}
summary{cursor:pointer;padding:11px 0;list-style:none;display:flex;gap:8px;align-items:baseline}
summary::-webkit-details-marker{display:none}summary span:nth-child(2){overflow-wrap:anywhere}summary .n{margin-left:auto;white-space:nowrap;font-variant-numeric:tabular-nums}
details[open] summary{border-bottom:1px solid var(--line)}details .body{padding:10px 0}
.upload{background:var(--panel);border:1px dashed var(--line);border-radius:10px;padding:14px}
button,select,.btn{font:inherit;color:var(--text);background:#222734;border:1px solid var(--line);border-radius:8px;padding:9px 12px}
.btn{display:inline-block;text-decoration:none}label.file{display:inline-block}label.file input{display:none}
a{color:var(--accent)}footer{margin-top:36px;color:var(--muted);font-size:12px}
"""


def _tile(n, label):
    return f'<div class="tile"><b>{n:,}</b><span>{escape(label)}</span></div>'


def _rows_table(rows, columns):
    head = "".join(f"<th>{escape(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{escape('' if r.get(c) is None else str(r.get(c)))}</td>" for c in columns) + "</tr>"
                   for r in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render(out, cfg):
    s, ev, rc = out["summary"], out["eval"], cfg["report"]
    landing = out["tables"]["landing"]
    by_id = {n: {r[ROW_ID]: r for r in t["rows"]} for n, t in landing.items()}
    handled = sum(f["pass"] for f in ev["faults"])
    verdict_ok = ev["pass"] and not s["baseline_failures"]
    verdict = (f"Eval {'passed' if verdict_ok else 'FAILED'}: {handled}/{len(ev['faults'])} faults handled as expected · "
               f"{len(ev['false_positives'])} false alarms · clean source {'passes' if not s['baseline_failures'] else 'FAILS'} every check")

    fault_rows = "".join(
        f"<tr><td>{escape(f['fault'])}<br><span class='muted small'>{escape(f['kind'])}</span></td><td class='num'>{f['injected']}</td>"
        f"<td>{escape(f['expect'])}</td><td class='{'ok' if f['pass'] else 'no'}'>{'✓' if f['pass'] else '✗ ' + escape(f['got'])}</td></tr>"
        for f in sorted(ev["faults"], key=lambda f: (f["pass"], f["fault"])))

    order = {"fail": 0, "error": 1, "skipped": 2, "pass": 3}
    checks_html = []
    for r in sorted(out["results"], key=lambda r: (order[r["status"]], r["id"])):
        if r["status"] == "pass":
            continue
        cls = {"fail": "no", "error": "no", "skipped": "skip"}[r["status"]]
        n = f"{len(r['rows']):,} rows" if r["level"] == "row" else r["status"]
        body = f"<p class='muted small'>{escape(r['description'])}</p>"
        if r.get("detail"):
            body += f"<p class='small'>{escape(r['detail'])}</p>"
        if r["rows"]:
            cols = ([r["column"]] if r["column"] else []) + [c for c in landing[r["table"]]["columns"] if c != r["column"]]
            cols = ["_row_id"] + cols[: rc["sample_columns"] - 1]
            sample = [by_id[r["table"]][i] for i in r["rows"][: rc["sample_rows"]]]
            body += _rows_table(sample, cols)
        label = r["id"].split(".", 1)[1] if "." in r["id"] else r["id"]
        body = f"<p class='small'><code>{escape(r['id'])}</code></p>" + body
        checks_html.append(f"<details><summary><span class='{cls}'>●</span> <span>{escape(label)}</span>"
                           f"<span class='n {cls}'>{n}</span></summary><div class='body'>{body}</div></details>")
    passed = sum(r["status"] == "pass" for r in out["results"])

    by_kind = {}
    for e in out["repairs"]:
        by_kind.setdefault(e["repair"], []).append(e)
    repairs = [e for v in by_kind.values() for e in v[: rc["sample_rows"]]]
    repair_html = _rows_table(repairs, ["repair", "column", "row", "from", "to"]) if repairs else "<p class='muted'>None.</p>"

    # Data the in-browser checker needs: check SQL, contract columns, and the reference tables (dims) for FK checks.
    refs = {n: {"columns": t["columns"], "rows": [[r.get(c) for c in t["columns"]] for r in t["rows"]]}
            for n, t in out["tables"]["source"].items() if n != "FactCardiacEvents"}
    app = {"checks": out["checks"], "columns": out["contract_columns"], "refs": refs,
           "maxMb": MAX_UPLOAD_MB, "sampleRows": rc["sample_rows"]}
    app_json = json.dumps(app, separators=(",", ":")).replace("</", "<\\/")
    samples = rc["pages_url"].rstrip("/") + "/samples/"  # absolute, so the frozen snapshot's links still work

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(rc['title'])}: data contracts on synthetic health data</title>
<meta name="description" content="Data contracts catch injected faults in a synthetic health system warehouse.">
<style>{CSS}</style></head><body><main>
<h1>{escape(rc['title'])}</h1>
<p class="muted">Data contracts on a synthetic health system warehouse. Faults are injected on purpose; the contracts have to catch every one, and raise no false alarms on clean data.</p>
<span class="pill {'ok' if verdict_ok else 'no'}">{escape(verdict)}</span>
<div class="tiles">{_tile(s['rows_in'], 'rows landed')}{_tile(s['rows_clean'], 'clean')}{_tile(s['rows_repaired'], 'repaired')}{_tile(s['rows_quarantined'], 'quarantined')}{_tile(s['checks_failed'], f"of {s['checks']} checks failed")}</div>

<h2>Faults injected</h2>
<div class="scroll"><table><thead><tr><th>fault</th><th>rows</th><th>expect</th><th>result</th></tr></thead><tbody>{fault_rows}</tbody></table></div>
<p class="muted small">From <code>config/faults.yml</code>. Each row gets at most one fault, so every outcome traces back to its cause.</p>

<h2>Contract checks that fired</h2>
{''.join(checks_html) or "<p class='muted'>None.</p>"}
<p class="muted small">{passed} other checks passed. Contracts: <a href="{escape(rc['repo_url'])}/tree/main/contracts">contracts/*.odcs.yaml</a> (Open Data Contract Standard).</p>

<h2>Safe repairs</h2>
{repair_html}
<p class="muted small">{s['rows_repaired']} rows fixed without changing meaning (casing, whitespace, date formats). Anything ambiguous is quarantined instead.</p>

<h2>Check your own CSV</h2>
<div class="upload">
<p>Pick a CSV with the same columns as one of the tables. It's checked <b>on this device</b> with the same contract SQL; the file is never uploaded.</p>
<p><label class="file btn">Choose CSV<input id="file" type="file" accept=".csv,text/csv"></label>
<select id="table" aria-label="table"></select></p>
<p class="small muted">Try one: <a href="{escape(samples)}FactCardiacEvents_landing.csv">landing file with faults</a> · <a href="{escape(samples)}FactCardiacEvents_clean.csv">clean file</a></p>
<div id="status" class="small muted"></div><div id="out"></div>
</div>

<h2>How it works</h2>
<p class="small">generate (seeded) → inject faults → safe repairs → contract checks in DuckDB → clean / quarantine split → eval against what was injected. Every setting is in <code>config/</code>. Each contract also lists a SQL Server connection with env-var placeholders, so the same contract can be pointed at a work database later.</p>
<footer>All data is synthetic. <a href="{escape(rc['repo_url'])}">Source</a></footer>
</main>
<script type="application/json" id="app">{app_json}</script>
<script type="module">
const APP = JSON.parse(document.getElementById('app').textContent);
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const q = (n) => '"' + String(n).replaceAll('"', '""') + '"';
const tables = Object.keys(APP.columns);
$('table').innerHTML = '<option value="">auto-detect table</option>' + tables.map((t) => `<option>${{esc(t)}}</option>`).join('');
let dbp;
async function engine() {{
  dbp ??= (async () => {{
    const duckdb = await import('{DUCKDB_WASM}');
    const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
    const url = URL.createObjectURL(new Blob([`importScripts("${{bundle.mainWorker}}");`], {{type: 'text/javascript'}}));
    const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), new Worker(url));
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    URL.revokeObjectURL(url);
    return db;
  }})();
  return dbp;
}}
const rowsOf = (res) => res.toArray().map((r) => {{ const o = r.toJSON(); for (const k in o) if (typeof o[k] === 'bigint') o[k] = Number(o[k]); return o; }});
// Spreadsheet formula injection: a cell starting with = + @ (or - not followed by a digit) is prefixed with '
const safeCell = (v) => {{ const s = String(v ?? ''); const t = /^[=+@\\t\\r]|^-(?![0-9.])/.test(s) ? "'" + s : s; return /[",\\n]/.test(t) ? '"' + t.replaceAll('"', '""') + '"' : t; }};
$('file').addEventListener('change', async (e) => {{
  const file = e.target.files[0]; if (!file) return;
  $('out').innerHTML = '';
  if (file.size > APP.maxMb * 1e6) {{ $('status').textContent = `File is over ${{APP.maxMb}} MB.`; return; }}
  try {{
    $('status').textContent = 'Loading the checker (first time takes a few seconds)…';
    const text = await file.text();
    const header = (text.split(/\\r?\\n/, 1)[0] || '').split(',').map((h) => h.trim().replace(/^"|"$/g, ''));
    let target = $('table').value;
    if (!target) target = tables.map((t) => [t, APP.columns[t].filter((c) => header.includes(c)).length]).sort((a, b) => b[1] - a[1])[0][0];
    const db = await engine(); const con = await db.connect();
    await db.registerFileText('upload.csv', text);
    for (const t of tables) await con.query(`DROP TABLE IF EXISTS ${{q(t)}}`);
    for (const [t, ref] of Object.entries(APP.refs)) {{
      if (t === target) continue;
      await con.query(`CREATE TABLE ${{q(t)}} (_row_id BIGINT, ${{ref.columns.map((c) => q(c) + ' VARCHAR').join(', ')}})`);
      const vals = ref.rows.map((r, i) => '(' + [i + 1, ...r.map((v) => v == null ? 'NULL' : "'" + String(v).replaceAll("'", "''") + "'")].join(',') + ')').join(',');
      if (vals) await con.query(`INSERT INTO ${{q(t)}} VALUES ${{vals}}`);
    }}
    await con.query(`CREATE TABLE ${{q(target)}} AS SELECT row_number() OVER () AS _row_id, * FROM read_csv('upload.csv', header=true, all_varchar=true, nullstr='')`);
    const present = rowsOf(await con.query(`DESCRIBE ${{q(target)}}`)).map((r) => r.column_name);
    const results = [];
    for (const ch of APP.checks.filter((c) => c.table === target)) {{
      const r = {{ id: ch.id, description: ch.description, rows: [], status: 'pass' }};
      if (ch.kind === 'schema') {{
        const miss = APP.columns[target].filter((c) => !present.includes(c));
        if (miss.length) Object.assign(r, {{ status: 'fail', detail: 'missing: ' + miss.join(', ') }});
      }} else if (ch.needs.some((c) => !present.includes(c))) r.status = 'skipped';
      else {{
        try {{
          const rows = rowsOf(await con.query(ch.sql));
          if (ch.level === 'row') {{ r.rows = rows.map((x) => x._row_id); r.status = r.rows.length ? 'fail' : 'pass'; }}
          else r.status = Object.values(rows[0])[0] ? 'pass' : 'fail';
        }} catch (err) {{ Object.assign(r, {{ status: 'error', detail: err.message.split('\\n')[0] }}); }}
      }}
      results.push(r);
    }}
    const bad = new Map();
    for (const r of results) for (const id of r.rows) bad.set(id, [...(bad.get(id) || []), r.id]);
    const total = rowsOf(await con.query(`SELECT COUNT(*) AS n FROM ${{q(target)}}`))[0].n;
    const fired = results.filter((r) => r.status !== 'pass');
    let html = `<p><b>${{esc(file.name)}}</b> checked as <code>${{esc(target)}}</code>: ${{total.toLocaleString()}} rows, ${{bad.size.toLocaleString()}} would be quarantined, ${{fired.length}} of ${{results.length}} checks fired.</p><p class="muted small">Safe repairs (casing, date formats) only run in the pipeline, so here those rows count as quarantined.</p>`;
    for (const r of fired) {{
      let body = `<p class="muted small">${{esc(r.description)}}</p>` + (r.detail ? `<p class="small">${{esc(r.detail)}}</p>` : '');
      if (r.rows.length) {{
        const ids = r.rows.slice(0, APP.sampleRows).join(',');
        const sample = rowsOf(await con.query(`SELECT * FROM ${{q(target)}} WHERE _row_id IN (${{ids}}) ORDER BY _row_id`));
        const cols = Object.keys(sample[0] || {{}}).slice(0, 6);
        body += '<div class="scroll"><table><thead><tr>' + cols.map((c) => `<th>${{esc(c)}}</th>`).join('') + '</tr></thead><tbody>' +
          sample.map((s) => '<tr>' + cols.map((c) => `<td>${{esc(s[c])}}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>';
      }}
      const cls = r.status === 'skipped' ? 'skip' : 'no';
      html += `<details><summary><span class="${{cls}}">●</span> <span>${{esc(r.id.split('.').slice(1).join('.'))}}</span><span class="n ${{cls}}">${{r.rows.length ? r.rows.length.toLocaleString() + ' rows' : r.status}}</span></summary><div class="body">${{body}}</div></details>`;
    }}
    if (bad.size) html += '<p><button id="dl">Download quarantine CSV</button></p>';
    $('out').innerHTML = html; $('status').textContent = 'Checked on this device. Nothing was uploaded.';
    if (bad.size) $('dl').onclick = async () => {{
      const ids = [...bad.keys()].join(',');
      const rows = rowsOf(await con.query(`SELECT * FROM ${{q(target)}} WHERE _row_id IN (${{ids}}) ORDER BY _row_id`));
      const cols = Object.keys(rows[0]);
      const csv = [[...cols, '_reasons'].map(safeCell).join(','), ...rows.map((r) => [...cols.map((c) => safeCell(r[c])), safeCell(bad.get(r._row_id).join('; '))].join(','))].join('\\n');
      const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], {{type: 'text/csv'}})); a.download = 'quarantine_' + target + '.csv'; a.click();
    }};
  }} catch (err) {{ $('status').textContent = "Couldn't check that file: " + err.message; console.error(err); }}
}});
</script></body></html>
"""
