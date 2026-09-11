import { TRACKS, type Track } from '@/data/tracks';

export interface SearchHit {
  track: Track;
  /** Only the AI engine explains its matches. */
  explanation?: string;
}

function normalise(s: string): string {
  return s.toLowerCase().trim();
}

/** Keyword search: every whitespace-separated term must appear in title, artist or genre. */
export function keywordSearch(query: string, tracks: Track[] = TRACKS): SearchHit[] {
  const terms = normalise(query).split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [];
  return tracks
    .filter((t) => {
      const hay = normalise(`${t.title} ${t.artist} ${t.genre}`);
      return terms.every((term) => hay.includes(term));
    })
    .map((track) => ({ track }));
}

/** Intent words the "AI" engine understands (a tiny stand-in for a real model). */
const INTENTS: Record<string, string[]> = {
  focus: ['focus', 'work', 'study', 'concentrate', 'coding'],
  sleep: ['sleep', 'calm', 'relax', 'chill', 'wind'],
  drive: ['drive', 'driving', 'road', 'trip', 'commute'],
  night: ['night', 'late', 'midnight', 'neon'],
  morning: ['morning', 'wake', 'coffee'],
  summer: ['summer', 'beach', 'sun'],
  upbeat: ['upbeat', 'happy', 'energy', 'party', 'workout'],
  retro: ['retro', '80s', 'synth'],
};

/**
 * "AI" search: keyword matches first, then tracks whose tags match the intent
 * words in the query, each with a one-line explanation. Deterministic and
 * offline — the point is the *product* difference behind the flag, not the model.
 */
export function aiSearch(query: string, tracks: Track[] = TRACKS): SearchHit[] {
  const q = normalise(query);
  if (!q) return [];
  const terms = q.split(/\s+/).filter(Boolean);
  const wantedTags = Object.entries(INTENTS)
    .filter(([, words]) => words.some((w) => terms.some((t) => t.startsWith(w) || w.startsWith(t))))
    .map(([tag]) => tag);

  const hits: SearchHit[] = [];
  const seen = new Set<string>();
  for (const { track } of keywordSearch(query, tracks)) {
    seen.add(track.id);
    hits.push({ track, explanation: `Title, artist or genre matches "${query.trim()}".` });
  }
  if (wantedTags.length > 0) {
    for (const track of tracks) {
      if (seen.has(track.id)) continue;
      const matched = track.tags.filter((tag) => wantedTags.includes(tag));
      if (matched.length === 0) continue;
      seen.add(track.id);
      hits.push({ track, explanation: `Fits a ${matched.join(' + ')} mood — similar to what you play at this time.` });
    }
  }
  return hits;
}
