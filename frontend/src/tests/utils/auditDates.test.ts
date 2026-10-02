import { isDayRangeReversed, localDayRange, localMidnightIso } from '@/utils/auditDates';

/** Local calendar date of an instant, as `YYYY-MM-DD`. */
function localDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// Month and year ends, a leap day, and the days clocks change in the US and
// Europe, so a zone with daylight saving meets its awkward days.
const DAYS: Array<[string, string]> = [
  ['2024-01-15', '2024-01-16'],
  ['2024-01-31', '2024-02-01'],
  ['2024-02-29', '2024-03-01'],
  ['2023-02-28', '2023-03-01'],
  ['2024-03-10', '2024-03-11'],
  ['2024-03-31', '2024-04-01'],
  ['2024-10-27', '2024-10-28'],
  ['2024-11-03', '2024-11-04'],
  ['2024-12-31', '2025-01-01'],
];

// These hold in whatever zone the test runs in: the instant sent, read back
// in the browser's zone, is midnight on the day picked (or the day after).
describe('localMidnightIso', () => {
  it.each(DAYS)('%s maps to local midnight on that day', (day) => {
    const iso = localMidnightIso(day) as string;
    const parsed = new Date(iso);
    expect(parsed.getHours()).toBe(0);
    expect(parsed.getMinutes()).toBe(0);
    expect(parsed.getSeconds()).toBe(0);
    expect(localDay(parsed)).toBe(day);
  });

  it.each(DAYS)('%s plus one day maps to local midnight on %s', (day, next) => {
    const parsed = new Date(localMidnightIso(day, 1) as string);
    expect(parsed.getHours()).toBe(0);
    expect(parsed.getMinutes()).toBe(0);
    expect(localDay(parsed)).toBe(next);
  });

  it('sends an ISO instant the API can parse', () => {
    expect(localMidnightIso('2024-05-03')).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });

  it.each(['', '2024-02-30', '2024-13-01', '2024-5-3', '03/05/2024', 'nonsense'])(
    'refuses %p',
    (bad) => {
      expect(localMidnightIso(bad)).toBeUndefined();
    },
  );
});

describe('localDayRange', () => {
  it('a one-day range spans that whole local day', () => {
    const { from_date, to_date } = localDayRange('2024-05-03', '2024-05-03');
    const from = new Date(from_date as string);
    const to = new Date(to_date as string);
    expect(localDay(from)).toBe('2024-05-03');
    expect(localDay(to)).toBe('2024-05-04');
    expect(from.getHours()).toBe(0);
    expect(to.getHours()).toBe(0);
    // The API refuses to_date <= from_date; a one-day range is not that.
    expect(to.getTime()).toBeGreaterThan(from.getTime());
  });

  it('a 23:00 local entry on the To day is inside the range, 00:30 the next day is not', () => {
    const { from_date, to_date } = localDayRange('2024-05-01', '2024-05-03');
    const lateOnTheDay = new Date(2024, 4, 3, 23, 0).getTime();
    const earlyNextDay = new Date(2024, 4, 4, 0, 30).getTime();
    const from = new Date(from_date as string).getTime();
    const to = new Date(to_date as string).getTime();
    expect(lateOnTheDay >= from && lateOnTheDay <= to).toBe(true);
    expect(earlyNextDay <= to).toBe(false);
  });

  it('leaves out an end that is not set', () => {
    expect(localDayRange(undefined, undefined)).toEqual({ from_date: undefined, to_date: undefined });
    expect(localDayRange('2024-05-03', undefined).to_date).toBeUndefined();
    expect(localDayRange(undefined, '2024-05-03').from_date).toBeUndefined();
  });
});

describe('isDayRangeReversed', () => {
  it.each([
    ['2024-05-03', '2024-05-02', true],
    ['2024-05-03', '2024-05-03', false],
    ['2024-05-03', '2024-05-04', false],
    ['2024-12-31', '2025-01-01', false],
    [undefined, '2024-05-02', false],
    ['2024-05-03', undefined, false],
  ])('from %p to %p reversed: %p', (start, end, expected) => {
    expect(isDayRangeReversed(start, end)).toBe(expected);
  });
});
