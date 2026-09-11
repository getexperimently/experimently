import { aiSearch, keywordSearch } from '@/lib/search';
import { chronologicalFeed, recommendedFeed, TRACKS } from '@/data/tracks';

describe('search engines', () => {
  it('keyword search matches title/artist/genre only and explains nothing', () => {
    const hits = keywordSearch('lumen');
    expect(hits.map((h) => h.track.id)).toEqual(['trk-001', 'trk-008']);
    expect(hits.every((h) => h.explanation === undefined)).toBe(true);
    expect(keywordSearch('late night drive')).toEqual([]);
    expect(keywordSearch('   ')).toEqual([]);
  });

  it('AI search understands moods and explains every hit', () => {
    const hits = aiSearch('late night drive');
    expect(hits.length).toBeGreaterThan(0);
    expect(hits.every((h) => typeof h.explanation === 'string' && h.explanation.length > 0)).toBe(true);
    expect(hits.some((h) => h.track.tags.includes('night') || h.track.tags.includes('drive'))).toBe(true);
    // keyword matches come first, with their own explanation
    expect(aiSearch('lumen')[0]).toMatchObject({ track: { id: 'trk-001' }, explanation: 'Title, artist or genre matches "lumen".' });
    expect(aiSearch('')).toEqual([]);
  });
});

describe('feeds', () => {
  it('classic feed is newest first and the recommended feed is a different order of the same tracks', () => {
    const classic = chronologicalFeed();
    expect(classic[0].id).toBe('trk-001');
    expect(classic[classic.length - 1].id).toBe('trk-010');
    const recs = recommendedFeed();
    expect(recs).toHaveLength(TRACKS.length);
    expect(recs.map((t) => t.id)).not.toEqual(classic.map((t) => t.id));
    expect(new Set(recs.map((t) => t.id)).size).toBe(TRACKS.length);
  });
});
