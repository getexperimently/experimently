import React from 'react';
import type { Track } from '@/data/tracks';
import type { ScreenId } from '@/lib/screens';

/** Square gradient artwork for a track (no images anywhere in the demo). */
export function Art({ track, size = 48, className = '' }: { track: Track; size?: number; className?: string }) {
  const style = { '--art-a': track.art[0], '--art-b': track.art[1], width: size, height: size } as React.CSSProperties;
  return <div className={`art flex-none ${className}`} style={style} aria-hidden="true" />;
}

/** Title row at the top of a phone screen. */
export function ScreenHeader({ id, title, subtitle, badge }: { id: string; title: string; subtitle?: string; badge?: React.ReactNode }) {
  return (
    <header className="mb-3 flex items-start justify-between gap-2">
      <div>
        <h2 id={id} className="text-xl font-bold leading-tight">
          {title}
        </h2>
        {subtitle && <p className="text-xs text-neutral-400">{subtitle}</p>}
      </div>
      {badge}
    </header>
  );
}

/** Small experiment/flag marker shown inside the phone so the audience sees the binding. */
export function Binding({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-white/15 px-2 py-0.5 font-mono text-[10px] text-neutral-300" data-testid="binding">
      {children}
    </span>
  );
}

const ICONS: Record<ScreenId, React.ReactNode> = {
  home: (
    <path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z" />
  ),
  player: <path d="M6 4l14 8-14 8z" />,
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.5 15.5 21 21" />
    </>
  ),
  notifications: (
    <>
      <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </>
  ),
  profile: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  onboarding: (
    <>
      <path d="M4 6h16M4 12h10M4 18h6" />
    </>
  ),
  payments: (
    <>
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M3 10h18" />
    </>
  ),
};

export function TabIcon({ id }: { id: ScreenId }) {
  return (
    <svg
      className="phone-tab-icon"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICONS[id]}
    </svg>
  );
}
