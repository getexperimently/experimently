import { countCsvEntries, countJsonEntries, exportFilename } from '@/utils/auditExport';

const HEADER = 'id,timestamp,reason\r\n';

describe('countCsvEntries', () => {
  it('counts rows after the header', () => {
    expect(countCsvEntries(HEADER)).toBe(0);
    expect(countCsvEntries(`${HEADER}1,t,a\r\n2,t,b\r\n`)).toBe(2);
  });

  it('keeps quoted commas, quotes and line breaks inside one row', () => {
    expect(countCsvEntries(`${HEADER}1,t,"a, ""b""\r\nc"\r\n2,t,x\r\n`)).toBe(2);
  });

  it('refuses a body that ends inside a row', () => {
    expect(countCsvEntries(`${HEADER}1,t,a\r\n2,t,b`)).toBeNull();
    expect(countCsvEntries(`${HEADER}1,t,"a\r\n`)).toBeNull();
    expect(countCsvEntries('')).toBeNull();
  });
});

describe('countJsonEntries', () => {
  it('counts the array and refuses anything else', () => {
    expect(countJsonEntries('[]')).toBe(0);
    expect(countJsonEntries('[{"id":"1"},{"id":"2"}]')).toBe(2);
    expect(countJsonEntries('[{"id":"1"}')).toBeNull();
    expect(countJsonEntries('{}')).toBeNull();
  });
});

describe('exportFilename', () => {
  it('is audit-log-<UTC>.<format>', () => {
    const at = new Date(Date.UTC(2026, 9, 4, 9, 5, 7, 123));
    expect(exportFilename('csv', at)).toBe('audit-log-20261004T090507Z.csv');
    expect(exportFilename('json', at)).toBe('audit-log-20261004T090507Z.json');
  });
});
