/**
 * Two rules over the Segments dashboard code (#440 PR D; gates-D D7, D24):
 *
 * - a destructive action is confirmed in the page, never with
 *   `window.confirm` (which a browser may suppress, and which axe and the
 *   journeys cannot see);
 * - the copy says what fail-closed evaluation does: no sentence claims a
 *   condition "matches every user", and nothing says the upgrade converts
 *   saved segments (EM C4).
 */
import fs from 'fs';
import path from 'path';

const SRC = path.join(__dirname, '..', '..');

const FILES = [
  'pages/segments/index.tsx',
  'pages/segments/new.tsx',
  'pages/segments/[id].tsx',
  'components/segments/IdUpload.tsx',
  'components/segments/segmentForm.ts',
  'components/segments/segmentLabels.ts',
  'components/targeting/SegmentPicker.tsx',
  'utils/segmentErrors.ts',
  'utils/segmentIds.ts',
  'utils/segmentPermissions.ts',
  'utils/segmentRules.ts',
  'utils/segmentUpload.ts',
];

const read = (file: string) => fs.readFileSync(path.join(SRC, file), 'utf8');

describe('Segments dashboard sources', () => {
  it('every listed file exists, so the checks below are not vacuous', () => {
    for (const file of FILES) expect(read(file).length).toBeGreaterThan(100);
  });

  it('no file calls confirm()', () => {
    const hits = FILES.filter((file) => /\b(window\.)?confirm\s*\(/.test(read(file)));
    expect(hits).toEqual([]);
  });

  it('no file says a condition matches every user, or that segments are converted', () => {
    const hits = FILES.flatMap((file) => {
      const text = read(file).replace(/\s+/g, ' ');
      return [/matches every user/i, /\bconvert/i].filter((re) => re.test(text)).map((re) => `${file}: ${re}`);
    });
    expect(hits).toEqual([]);
  });
});
