# data_cleaner

A data quality gate for a fake hospital dataset. Plain-language glossary: **contract** = the written rules for a table, **fault** = an error planted on purpose, **repair** = auto-fix, **quarantine** = held back with a reason, **eval** = the scorecard.

Data contracts on a synthetic health system warehouse. Faults are injected on purpose; the contracts have to catch every one, safe repairs fix what can't change meaning, the rest is quarantined with reasons, and an eval proves it against what was injected. Built for showing data quality patterns, phone-first.

```
generate (seeded) -> inject faults -> safe repairs -> contract checks (DuckDB) -> clean / quarantine -> eval -> report
```

## Run
```
pip install -r requirements.txt
python -m data_cleaner          # writes out/ (data) and site/index.html (report); exits 1 if the eval fails
```

## Test
```
pytest -q                       # CI runs this, node --test, and the pipeline itself
```

## Deployed
- Live: https://leftbrain847.github.io/data_cleaner/ (rebuilt by `.github/workflows/pages.yml` on every merge to main)
- Day snapshot: `2026-11-27 - data_cleaner` (frozen; never edited)

## Where things live
| Path | What |
|---|---|
| `config/pipeline.yml` | paths, seed, which server a contract runs against, report settings |
| `config/faults.yml` | fault catalog: turn faults on/off, change rates, add new ones, say what should happen |
| `config/repairs.yml` | safe repairs (canonical enum casing, alternate date formats) |
| `contracts/*.odcs.yaml` | one contract per table, [Open Data Contract Standard](https://bitol-io.github.io/open-data-contract-standard/) v3 style |
| `source/generate_synthetic_data.py` | seeded generator, vendored from `leftbrain847/portfolio` (same data, byte for byte) |
| `data_cleaner/` | the pipeline: `faults`, `repairs`, `contracts` (ODCS -> SQL), `engine` (DuckDB), `pipeline`, `report` |

## What a contract can say (and gets enforced)
Property: `required`, `unique`, `logicalType` (integer, number, date, string), `logicalTypeOptions` (`minimum`, `maximum`, `pattern`), `relationships[].to`, `quality[]` with `metric: invalidValues`.
Table: every contract column arrives (schema drift), `metric: rowCount` with `mustBeBetween`, `type: sql` rules with `mustBe: 0`. A SQL rule written as `SELECT COUNT(*) FROM ... WHERE ...` becomes a row check, so failing rows get quarantined.
Other ODCS fields are carried but not executed.

## Check your own CSV (on the report page)
The page runs the same contract SQL in the browser with DuckDB-WASM (pinned version, loaded from jsDelivr). The file is read on the device and never uploaded; nothing a visitor picks reaches this repo or any server. Column names are quoted, values are escaped before display, and the downloadable quarantine CSV neutralizes spreadsheet formulas. No model reads uploaded files.

## Pointing a contract at SQL Server
Each contract lists a `work_sqlserver` server with `${SQLSERVER_HOST}` / `${SQLSERVER_DATABASE}` placeholders: never commit real values. Running the checks there is the next step (the check SQL is plain ANSI apart from DuckDB's `TRY_CAST`/`regexp_matches`, which map to T-SQL `TRY_CAST`/`LIKE` patterns).

## Ship a sprint day
```
node scripts/snapshot.mjs site/index.html --public
```
Commit `snapshots/` (via PR). The index's nightly refresh logs the day.
