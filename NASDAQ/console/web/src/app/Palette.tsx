// ⌘K command palette: holdings, screens and actions. Enter opens the first
// match, Esc closes. Ported from vmPalette.

import { useState } from 'react';
import { cx } from '@/lib/format';
import { control, drawer, nav, type Intent, type Screen } from '@/domain/actions';
import { Icon } from '@/components/icons';
import { useConsole, useCtx } from './console';

interface Item {
  l: string;
  s: string;
  k: string;
  intent: Intent | 'theme';
  tc: string;
}

const SCREENS: [Screen, string, string][] = [
  ['overview', 'Overview', 'g o'], ['holdings', 'Holdings', 'g h'], ['orders', 'Orders', 'g r'], ['performance', 'Performance', 'g p'],
  ['compliance', 'Compliance', 'g c'], ['controls', 'Controls', 'g x'], ['agent', 'Agent', 'g a'], ['health', 'Health', 'g e'],
  ['alerts', 'Alerts', 'g l'], ['audit', 'Audit log', 'g u'], ['roadmap', 'Roadmap', 'g m'], ['glossary', 'Glossary', 'g y'], ['settings', 'Settings', 'g s'],
];

export function Palette() {
  const { positions, setPalette, dispatch, theme, setTheme } = useConsole();
  const ctx = useCtx();
  const [q, setQ] = useState('');
  const own = ctx.role === 'owner';
  const needle = q.trim().toLowerCase();
  const match = (i: Item) => !needle || (i.l + ' ' + i.s).toLowerCase().includes(needle);
  const review = positions.find((h) => h.review);
  const acts: (Item & { own: boolean })[] = [
    { l: 'STOP TRADING', s: 'kill switch · immediate', k: 'action', intent: control('stop'), tc: 'danger b', own: true },
    { l: 'Pause entries', s: 'tonight’s 19:15 submit', k: 'action', intent: control('pause'), tc: '', own: true },
    { l: 'Re-run Cycle A', s: 'workflow_dispatch · idempotent', k: 'action', intent: control('rerun', 'Cycle A'), tc: '', own: true },
    ...(review ? [{ l: 'Force exit ' + review.symbol, s: 'Sharia · next open', k: 'action', intent: control('force_exit', review.symbol), tc: '', own: true }] : []),
    { l: 'Toggle theme', s: theme === 'dark' ? 'switch to light' : 'switch to dark', k: 'display', intent: 'theme', tc: '', own: false },
  ];
  const groups = [
    { l: 'Holdings', items: positions.map((h): Item => ({ l: h.symbol, s: h.name, k: 'holding', intent: drawer(h.symbol), tc: 'sym' })).filter(match) },
    { l: 'Screens', items: SCREENS.filter((x) => own || x[0] !== 'controls').map(([k, l, key]): Item => ({ l, s: '', k: key, intent: nav(k), tc: '' })).filter(match) },
    { l: 'Actions', items: acts.filter((a) => own || !a.own).filter(match) },
  ].filter((g) => g.items.length);
  const first = groups[0]?.items[0];
  const run = (i: Item) => {
    setPalette(false);
    if (i.intent === 'theme') setTheme(theme === 'dark' ? 'light' : 'dark');
    else dispatch(i.intent);
  };
  return (
    <div className="pal">
      <button type="button" className="dscrim" style={{ opacity: 0, top: 0 }} onClick={() => setPalette(false)} aria-label="Close command palette" tabIndex={-1} />
      <div className="pal-box" role="dialog" aria-label="Command palette" style={{ position: 'relative', zIndex: 1 }}>
        <div style={{ position: 'relative' }}>
          <Icon name="search" style={{ position: 'absolute', left: 16, top: 17, color: 'var(--fg-3)' }} />
          <input
            className="pal-in" type="text" autoFocus placeholder="Search symbols, screens and actions…" value={q} aria-label="Command"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setPalette(false);
              else if (e.key === 'Enter' && first) run(first);
            }}
          />
        </div>
        <div className="pal-l">
          {groups.map((g) => (
            <div key={g.l}>
              <div className="pal-g">{g.l}</div>
              {g.items.map((i) => (
                <button key={g.l + i.l} type="button" className={cx('pal-i', i === first && 'hi')} onClick={() => run(i)}>
                  <span className={i.tc}>{i.l}</span><span className="xs muted">{i.s}</span><span className="k">{i.k}</span>
                </button>
              ))}
            </div>
          ))}
          {!groups.length && <div className="pb sm muted">No matches.</div>}
        </div>
        <div className="pf xs muted"><span>↵ open first match</span><span>esc close</span><span className="sp" /><span className="wide-only">⌘K toggles</span></div>
      </div>
    </div>
  );
}
