/**
 * An ARIA tablist with arrow-key navigation (Left/Right, Home/End) and
 * labelled panels, per the warehouse UX draft.
 */
import React, { ReactNode, useRef } from 'react';

export interface TabSpec<K extends string> {
  key: K;
  label: string;
}

export function Tabs<K extends string>({
  idPrefix,
  label,
  tabs,
  selected,
  onSelect,
  children,
}: {
  idPrefix: string;
  label: string;
  tabs: TabSpec<K>[];
  selected: K;
  onSelect: (key: K) => void;
  children: ReactNode;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const move = (index: number) => {
    const tab = tabs[(index + tabs.length) % tabs.length];
    onSelect(tab.key);
    refs.current[tab.key]?.focus();
  };
  const onKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key === 'ArrowRight') move(index + 1);
    else if (e.key === 'ArrowLeft') move(index - 1);
    else if (e.key === 'Home') move(0);
    else if (e.key === 'End') move(tabs.length - 1);
    else return;
    e.preventDefault();
  };
  return (
    <div>
      <div role="tablist" aria-label={label} className="mb-4 flex gap-1 border-b border-slate-200">
        {tabs.map((t, i) => {
          const active = t.key === selected;
          return (
            <button
              key={t.key}
              ref={(el) => {
                refs.current[t.key] = el;
              }}
              id={`${idPrefix}-tab-${t.key}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls={`${idPrefix}-panel-${t.key}`}
              tabIndex={active ? 0 : -1}
              onClick={() => onSelect(t.key)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-600 ${
                active ? 'border-blue-700 text-blue-800' : 'border-transparent text-slate-700 hover:text-slate-900'
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`${idPrefix}-panel-${selected}`}
        aria-labelledby={`${idPrefix}-tab-${selected}`}
        tabIndex={0}
        className="focus:outline-none"
      >
        {children}
      </div>
    </div>
  );
}

export default Tabs;
