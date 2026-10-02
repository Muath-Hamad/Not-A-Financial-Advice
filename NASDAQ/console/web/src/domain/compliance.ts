// Compliance screen: per-holding Sharia cards, the universe and watchlist,
// re-screen diffs. Ported from vmComp.

import type { CompliancePayload, Position, UniverseName } from '@/api/types';
import { f } from '@/lib/format';
import { onWatch } from './overview';
import { sharia, type ShariaCard } from './core';
import type { Ctx } from './ctx';

export type UniFilter = 'all' | 'watch' | 'review' | 'excl' | 'held';

export interface ComplianceCard extends ShariaCard {
  s: string;
  n: string;
  w: string;
}

/** Holding cards, anything not graded A first. */
export function selectCards(c: Ctx, positions: Position[]): ComplianceCard[] {
  return positions
    .map((h) => ({ s: h.symbol, n: h.name, w: f(((h.shares * h.last) / c.equity) * 100, 1) + '%', ...sharia(h, c) }))
    .sort((a, b) => (a.g === 'A' ? 1 : 0) - (b.g === 'A' ? 1 : 0));
}

interface UniRow extends Pick<UniverseName, 'symbol' | 'name' | 'grade' | 'status' | 'debtPct' | 'cashPct' | 'flag'> {
  held: boolean;
}

const headroom = (v: number | null) => {
  if (v == null) return { t: '—', cls: 'dim' };
  const x = 30 - v;
  return { t: (x >= 0 ? '' : '−') + f(Math.abs(x), 1) + ' pp', cls: x < 0 ? 'danger' : x < 3 ? 'warn' : x < 10 ? '' : 'dim' };
};

export function selectUniverse(c: Ctx, positions: Position[], p: CompliancePayload, filter: UniFilter) {
  const held: UniRow[] = positions.map((h) => {
    const s = sharia(h, c);
    return {
      symbol: h.symbol, name: h.name, grade: s.g, status: s.short, debtPct: h.debtPct, cashPct: h.cashPct,
      flag: h.review && s.short !== 'Excluded' ? (h.review.keyword + ' — D1 ruling due 30 Oct') : s.short === 'Excluded' ? 'owner exclusion — forced exit queued' : '',
      held: true,
    };
  });
  const all: UniRow[] = held.concat(p.universe.map((u) => ({ ...u, held: false })));
  const list = all.filter((u) => filter === 'all'
    || (filter === 'watch' && onWatch(u))
    || (filter === 'review' && u.status === 'Under review')
    || (filter === 'excl' && u.status === 'Excluded')
    || (filter === 'held' && u.held));
  return {
    rows: list.map((u) => {
      const d = headroom(u.debtPct);
      const ch = headroom(u.cashPct);
      return {
        s: u.symbol, n: u.name, st: u.status,
        stCls: u.status === 'Compliant' ? 'pos' : u.status === 'Under review' ? 'warn' : 'danger',
        g: u.grade, gCls: 'g' + u.grade,
        dh: d.t, dCls: d.cls, d: u.debtPct == null ? 'n/a' : f(u.debtPct, 1) + '%',
        ch: ch.t, cCls: ch.cls, c: u.cashPct == null ? 'n/a' : f(u.cashPct, 1) + '%',
        flag: u.flag || (onWatch(u) ? 'watchlist: within 3 pp of the 30% line' : ''),
        held: u.held ? 'Held' : '—',
      };
    }),
    hint: list.length + ' shown of the ' + p.universeSize + '-name universe',
    foot: 'Showing ' + list.length + ' of ' + p.universeSize + ' · watchlist ' + all.filter(onWatch).length + ' · review-flagged ' + p.reviewFlagged + ' · excluded: ' + p.excludedAfterRescreen,
  };
}

export function selectRescreen(p: CompliancePayload, id: string) {
  const sel = p.rescreens.find((r) => r.id === id) || p.rescreens[0];
  return {
    list: p.rescreens.map((r) => ({ id: r.id, d: r.date, k: r.kind, sum: r.summary, dot: r.dot, on: r.id === sel.id })),
    sel: {
      d: sel.date, k: sel.kind, file: sel.file, stats: sel.stats, h1: sel.outTitle,
      out: sel.out.map((o) => ({ s: o.symbol, r: o.reason, t: sel.outTag, cls: 'danger' })),
      h2: sel.inTitle, inn: sel.in, note2: sel.inNote, note: sel.note, noteCls: sel.noteCls,
    },
  };
}
