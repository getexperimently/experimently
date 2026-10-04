/**
 * Checks on a downloaded audit log export (#221) before the page saves it.
 *
 * The API sends `X-Total-Count`, the number of entries the file should hold.
 * A body cut short still arrives with a 200, so the page counts what it
 * received and saves the file only when the two agree.
 */

/**
 * The number of entries in an export CSV (rows after the header), or `null`
 * when the text does not end with a complete row. Quoted cells may hold
 * commas, quotes and line breaks (RFC 4180).
 */
export function countCsvEntries(text: string): number | null {
  let records = 0;
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === '"') {
      inQuotes = !inQuotes;
    } else if (ch === '\n' && !inQuotes) {
      records += 1;
    }
  }
  if (inQuotes || !text.endsWith('\n') || records < 1) return null;
  return records - 1;
}

/** The number of entries in an export JSON array, or `null` if it does not parse. */
export function countJsonEntries(text: string): number | null {
  try {
    const parsed: unknown = JSON.parse(text);
    return Array.isArray(parsed) ? parsed.length : null;
  } catch {
    return null;
  }
}

/** `audit-log-<UTC YYYYMMDDTHHMMSSZ>.<format>`, the name the API gives the file. */
export function exportFilename(format: 'csv' | 'json', now: Date = new Date()): string {
  const stamp = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  return `audit-log-${stamp}.${format}`;
}
