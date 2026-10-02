/**
 * The audit log page's date pickers hold calendar days (`YYYY-MM-DD`, what
 * `<input type="date">` gives). The table shows each entry's time in the
 * browser's local zone (`toLocaleString()`), so a day picked here is that
 * same LOCAL day: "From 3 May" starts at local midnight on 3 May, and
 * "To 5 May" ends at local midnight starting 6 May, so the whole of 5 May is
 * in. The API (`from_date`/`to_date`) takes instants, sent as ISO strings.
 */

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Local midnight at the start of `day` plus `addDays`, as an ISO string, or
 * `undefined` when `day` is not a real calendar date.
 */
export function localMidnightIso(day: string, addDays = 0): string | undefined {
  const match = DAY.exec(day);
  if (!match) return undefined;
  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const date = Number(match[3]);
  const parsed = new Date(year, month, date);
  // `new Date` rolls 31 February over into March; refuse it instead.
  if (parsed.getFullYear() !== year || parsed.getMonth() !== month || parsed.getDate() !== date) {
    return undefined;
  }
  return new Date(year, month, date + addDays).toISOString();
}

/** True when both days are set and the end is before the start. */
export function isDayRangeReversed(start?: string, end?: string): boolean {
  return Boolean(start && end && end < start);
}

/**
 * The `from_date`/`to_date` pair for an inclusive range of local days. Either
 * end may be missing. A one-day range (start = end) spans that whole day.
 */
export function localDayRange(
  start?: string,
  end?: string,
): { from_date?: string; to_date?: string } {
  return {
    from_date: start ? localMidnightIso(start) : undefined,
    to_date: end ? localMidnightIso(end, 1) : undefined,
  };
}
