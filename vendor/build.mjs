// Bundles DuckDB-WASM into ../site/vendor/ so the report page loads the checker from its own origin.
import { build } from 'esbuild';
import { copyFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

const out = new URL('../site/vendor/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const dist = dirname(createRequire(import.meta.url).resolve('@duckdb/duckdb-wasm/dist/duckdb-eh.wasm'));
await build({
  stdin: { contents: "export * from '@duckdb/duckdb-wasm';", resolveDir: new URL('.', import.meta.url).pathname },
  bundle: true, format: 'esm', minify: true, outfile: join(out, 'duckdb.mjs'), logLevel: 'error',
});
for (const f of ['duckdb-eh.wasm', 'duckdb-browser-eh.worker.js']) copyFileSync(join(dist, f), join(out, f));
console.log('vendored DuckDB-WASM into', out);
