/**
 * Every code the W4 backend can store as a run's `error_code` or a metric's
 * `not_computed_reason`, read from the backend source rather than typed here,
 * so a code added there fails the dashboard's tests until it has words.
 *
 * - `WarehouseErrorCode` members in modules/backend/app/warehouse/errors.py
 *   (failure_code() stores `exc.code.value` for any WarehouseError);
 * - the literal codes of `WarehouseResultRefused(...)` in the runner and the
 *   result parser (failure_code() stores `exc.code`);
 * - literal `error_code="..."` and `_not_computed(metric, "...")` in the runner.
 */
import fs from 'fs';
import path from 'path';

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..', '..');
const BACKEND = path.join(REPO_ROOT, 'modules', 'backend', 'app');

export const ERRORS_PY = path.join(BACKEND, 'warehouse', 'errors.py');
export const RUNNER_PY = path.join(BACKEND, 'services', 'warehouse_runner.py');
export const STATS_PY = path.join(BACKEND, 'services', 'warehouse_sufficient_stats.py');

/** `NAME = "value"` lines inside `class WarehouseErrorCode`. */
export function enumCodes(source: string): string[] {
  const start = source.indexOf('class WarehouseErrorCode(');
  if (start === -1) return [];
  const body = source.slice(start).split('\n').slice(1);
  const codes: string[] = [];
  for (const line of body) {
    if (/^\S/.test(line)) break; // the class body ended
    const m = /^\s+[A-Z][A-Z0-9_]*\s*=\s*"([a-z0-9_]+)"\s*$/.exec(line);
    if (m) codes.push(m[1]);
  }
  return codes;
}

/** Literal codes stored by the runner or raised as a result refusal. */
export function literalCodes(source: string): string[] {
  const found = new Set<string>();
  const patterns = [
    /WarehouseResultRefused\(\s*"([a-z0-9_]+)"/g,
    /error_code\s*=\s*"([a-z0-9_]+)"/g,
    /_not_computed\(\s*\w+\s*,\s*"([a-z0-9_]+)"/g,
  ];
  for (const re of patterns) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(source)) !== null) found.add(m[1]);
  }
  return Array.from(found);
}

/** Every storable code, sorted. */
export function storableCodes(): string[] {
  const read = (file: string) => fs.readFileSync(file, 'utf8');
  const all = new Set<string>([
    ...enumCodes(read(ERRORS_PY)),
    ...literalCodes(read(RUNNER_PY)),
    ...literalCodes(read(STATS_PY)),
  ]);
  return Array.from(all).sort();
}
