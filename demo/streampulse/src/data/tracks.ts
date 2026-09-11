/** A tiny made-up catalogue. No audio, no images — artwork is a CSS gradient. */
export interface Track {
  id: string;
  title: string;
  artist: string;
  genre: string;
  /** Seconds. */
  duration: number;
  /** ISO date; the classic feed sorts by this, newest first. */
  releasedAt: string;
  /** Two colours for the gradient artwork. */
  art: [string, string];
  /** Tags the AI search and the "For you" feed reason about. */
  tags: string[];
}

export const TRACKS: Track[] = [
  { id: 'trk-001', title: 'Neon Tide', artist: 'Lumen Fields', genre: 'Synthwave', duration: 214, releasedAt: '2026-08-30', art: ['#f43f5e', '#7c3aed'], tags: ['night', 'drive', 'retro'] },
  { id: 'trk-002', title: 'Paper Lanterns', artist: 'Mira Sato', genre: 'Indie folk', duration: 187, releasedAt: '2026-08-27', art: ['#f59e0b', '#ef4444'], tags: ['acoustic', 'calm', 'evening'] },
  { id: 'trk-003', title: 'Static Bloom', artist: 'The Circuits', genre: 'Electronic', duration: 243, releasedAt: '2026-08-21', art: ['#06b6d4', '#3b82f6'], tags: ['focus', 'work', 'ambient'] },
  { id: 'trk-004', title: 'Long Way Round', artist: 'Harbor & Vale', genre: 'Rock', duration: 262, releasedAt: '2026-08-14', art: ['#10b981', '#0f766e'], tags: ['drive', 'road', 'summer'] },
  { id: 'trk-005', title: 'Glasshouse', artist: 'Aria Nova', genre: 'Pop', duration: 198, releasedAt: '2026-08-09', art: ['#ec4899', '#f97316'], tags: ['upbeat', 'summer', 'morning'] },
  { id: 'trk-006', title: 'Quiet Engines', artist: 'Deep Meridian', genre: 'Ambient', duration: 331, releasedAt: '2026-07-31', art: ['#64748b', '#1e293b'], tags: ['focus', 'sleep', 'calm'] },
  { id: 'trk-007', title: 'Saffron Sky', artist: 'Kavi Rao', genre: 'World', duration: 226, releasedAt: '2026-07-22', art: ['#f97316', '#eab308'], tags: ['morning', 'travel', 'upbeat'] },
  { id: 'trk-008', title: 'Copper Wire', artist: 'Lumen Fields', genre: 'Synthwave', duration: 205, releasedAt: '2026-07-10', art: ['#8b5cf6', '#ec4899'], tags: ['night', 'retro', 'work'] },
  { id: 'trk-009', title: 'Tidewater', artist: 'Harbor & Vale', genre: 'Rock', duration: 251, releasedAt: '2026-06-28', art: ['#0ea5e9', '#14b8a6'], tags: ['road', 'summer', 'evening'] },
  { id: 'trk-010', title: 'Slow Orbit', artist: 'Deep Meridian', genre: 'Ambient', duration: 384, releasedAt: '2026-06-12', art: ['#334155', '#6366f1'], tags: ['sleep', 'calm', 'night'] },
];

export const TRACKS_BY_ID: Record<string, Track> = Object.fromEntries(TRACKS.map((t) => [t.id, t]));

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

/** Classic feed: newest release first. */
export function chronologicalFeed(tracks: Track[] = TRACKS): Track[] {
  return [...tracks].sort((a, b) => (a.releasedAt < b.releasedAt ? 1 : a.releasedAt > b.releasedAt ? -1 : 0));
}

/**
 * "For you" feed (recs v2): a deterministic re-ranking that favours the listener's
 * taste tags, so the two feeds visibly differ.
 */
export function recommendedFeed(tasteTags: string[] = ['night', 'focus', 'drive'], tracks: Track[] = TRACKS): Track[] {
  const score = (t: Track) => t.tags.filter((tag) => tasteTags.includes(tag)).length;
  return [...tracks].sort((a, b) => score(b) - score(a) || a.title.localeCompare(b.title));
}
