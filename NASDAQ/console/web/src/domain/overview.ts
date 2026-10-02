// Overview screen: KPIs, attention list, equity chart, phase ring and the
// compliance strip. Ported from attention, vmOverview, vmEquity, vmPhase,
// vmCompStrip.

import type { Decision, EquityMarker, Intent as OrderIntent, OverviewPayload, Position, UniverseName } from '@/api/types';
import { f, spark, spct, susd, tn, usd, type Tone } from '@/lib/format';
import { ago, dayLabel, wdLabel } from '@/lib/dates';
import { control, drawer, nav, type Intent } from './actions';
import { acctEquity, acctShares, confOf, exitOf, holdingRows, pendingRows, sharia, type HoldingRow } from './core';
import type { Ctx } from './ctx';

export interface AttentionItem {
  tone: 'red' | 'amber' | 'blue';
  t: string;
  s: string;
  btn: string;
  intent: Intent;
}

/** Drift of the account from the Model, as % of Model equity. */
export function driftPct(positions: Position[], c: Ctx): number {
  const v = positions.reduce((a, h) => a + Math.abs(acctShares(h) - h.shares) * h.last, 0);
  return (v / c.equity) * 100;
}

export function attention(c: Ctx, positions: Position[], intents: OrderIntent[], decisions: Decision[], nextOpen: string): AttentionItem[] {
  const A: AttentionItem[] = [];
  const acct = c.env !== 'ghost';
  const it = (tone: AttentionItem['tone'], t: string, s: string, btn: string, intent: Intent): AttentionItem => ({ tone, t, s, btn, intent });
  const fa = c.facts;
  const fl = fa.failing;
  if (c.data === 'stale' && fl) {
    const [what, why] = fl.reason.split(': ');
    A.push(it('red', 'Cycle A failed ' + fl.count + '× — ' + what.toLowerCase(), (why ?? fl.reason) + ' · book from ' + wdLabel(fa.model.asof), 'Details', nav('health')));
  }
  if (c.data === 'error') A.push(it('red', acct ? 'Broker unreachable' : 'Indexer unreachable', acct ? 'gateway timeout · last success ' + (fa.broker?.lastOk ?? '—') : 'ledger not synced for ' + ago(fa.ledger.downMin), 'Health', nav('health')));
  if (c.trading === 'halted') A.push(it('red', 'Reconciliation break' + (fa.halt ? ' — ' + fa.halt.symbol + ' ' + fa.halt.expected + ' vs ' + fa.halt.actual : ''), 'submit halted until cleared with a cause', 'Resolve', nav('controls')));
  if (c.trading === 'stopped') A.push(it('red', 'Trading stopped (kill switch)', 'since ' + (c.stopAt || '18:04 ET') + ' · preflight needed to resume', 'Resume…', { kind: 'preflight' }));
  if (c.trading === 'held') {
    const n = pendingRows(intents, positions, c).filter((o) => o.live).length;
    A.push(it('amber', 'Night held — release before 09:28 ET', 'approval mode · ' + n + ' order' + (n === 1 ? '' : 's') + ' waiting', 'Release', control('release')));
  }
  positions
    .filter((h) => h.review && !c.controls.forcedExits.includes(h.symbol))
    .forEach((h) => A.push(it('amber', h.symbol + ' review-flagged', (h.review?.keyword ?? '') + ' · ruling due ' + wdLabel(fa.d1Due) + ' (D1)', 'Review', drawer(h.symbol))));
  positions.forEach((h) => {
    const ex = exitOf(h);
    if (h.rankExit || ex.dist == null || ex.stopP == null || ex.dist >= 1) return;
    const cv = confOf(h, c);
    A.push(it('amber', h.symbol + ' ' + f(ex.dist, 1) + ' ATR above its ' + ex.stopK.toLowerCase(), 'stop ' + usd(ex.stopP) + ' · last ' + usd(h.last) + (cv ? ' · confidence ' + cv.tot + ' ' + cv.bandL : ''), 'View', drawer(h.symbol)));
  });
  if (acct && c.data !== 'stale') {
    const d = driftPct(positions, c);
    const off = positions.find((h) => acctShares(h) !== h.shares);
    if (d > 1.5 && off) {
      A.push(it('amber', 'Drift ' + f(d, 1) + '% > 1.5% band', off.symbol + ' account ' + acctShares(off) + ' vs Model ' + off.shares + (off.account?.drift ? ' — ' + off.account.drift.short : ''), 'Compare', nav('holdings', { book: 'side' })));
    }
  }
  if (c.data !== 'stale') {
    const day = wdLabel(nextOpen).split(' ')[0];
    const dayName = { Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday', Fri: 'Friday' }[day] ?? day;
    positions.filter((h) => h.rankExit).forEach((h) => {
      const sell = intents.find((o) => o.symbol === h.symbol && o.side === 'SELL');
      A.push(it('blue', h.symbol + ' rank exit at ' + dayName + '’s open', (h.rank != null ? 'rank ' + h.rank + ' > 30' : 'out of the top 30') + ' · sell ' + (sell ? sell.shares : h.shares) + ' sh queued', 'Orders', nav('orders', { tab: 'pending' })));
    });
  }
  decisions
    .filter((d) => d.status === 'Open' && d.daysLeft != null && d.daysLeft <= 21)
    .forEach((d) => A.push(it('blue', d.id + ' ' + d.title.split(' ')[0] + ' decision due ' + d.due.replace(/ \d{4}$/, ''), d.title.replace(/^\S+\s+(as an?\s+)?/, '') + ' — your call', 'Roadmap', nav('roadmap'))));
  return A;
}

export interface OverviewView {
  sub: string;
  eq: string;
  eqSince: string;
  eqCls: Tone;
  ixic: string;
  ixCls: Tone;
  sEq: string;
  eqAcct: string;
  day: string;
  dayP: string;
  dayCls: Tone;
  dayWhen: string;
  sDay: string;
  dayAcct: string;
  dd: string;
  peak: string;
  mdd: string;
  ddW: string;
  exp: string;
  cash: string;
  expW: string;
  expAcct: string;
  pos: string;
  posFree: string;
  largest: string;
  slots: boolean[];
  underRev: string;
  ord: string;
  ordSplit: string;
  ordWhen: string;
  ordBlk: boolean;
  ordBlkL: string;
  ordNote: string;
  att: AttentionItem[];
  attN: string;
  attCls: 'red' | 'warn';
  rows: HoldingRow[];
  snapHint: string;
}

export const MAX_POSITIONS = 15;

export function selectOverview(c: Ctx, o: OverviewPayload, positions: Position[], intents: OrderIntent[], decisions: Decision[], nextOpen: string): OverviewView {
  const M = o.equityCurve.map((p) => p.model);
  const B = o.equityCurve.map((p) => p.benchmark);
  const A = o.equityCurve.map((p) => p.account);
  const n = M.length;
  const acct = c.env !== 'ghost';
  const stale = c.data === 'stale';
  const rows = holdingRows(positions, intents, c, 'model');
  const aEq = acctEquity(positions, c);
  const pend = pendingRows(intents, positions, c);
  const live = pend.filter((x) => x.live);
  const blk = pend.filter((x) => x.guardrail);
  const buys = live.filter((x) => x.side === 'BUY').length;
  const sells = live.length - buys;
  let peak = 0;
  let pk = M[0];
  let mdd = 0;
  M.forEach((v) => { peak = Math.max(peak, v); pk = Math.max(pk, v); mdd = Math.min(mdd, v / pk - 1); });
  const dd = (M[n - 1] / peak - 1) * 100;
  const dayChg = M[n - 1] - M[n - 2];
  const aDay = A[n - 1] != null && A[n - 2] != null ? (A[n - 1] as number) - (A[n - 2] as number) : null;
  const T = c.trading;
  let ordNote = 'submit 19:15 ET · window closes 09:28 ET';
  if (T === 'held') ordNote = 'night held — release before 09:28 ET';
  if (T === 'stopped') ordNote = 'kill switch — nothing will be sent';
  if (T === 'halted') ordNote = 'halted — the submit sends nothing';
  if (c.released) ordNote = 'accepted by the broker 19:31 ET';
  if (stale) ordNote = 'no plan since ' + wdLabel(o.asof) + ' — Cycle A failing';
  const fa = c.facts;
  const blkRules = blk.map((x) => x.guardrail).filter((x, i, a) => a.indexOf(x) === i).join(', ');
  const invested = rows.reduce((a, r) => a + r._val, 0);
  const expPct = (1 - c.cash / c.equity) * 100;
  const aExp = c.accountCash != null ? (1 - c.accountCash / aEq) * 100 : 0;
  const largest = rows.reduce<HoldingRow | null>((m, r) => (!m || r._w > m._w ? r : m), null);
  const att = attention(c, positions, intents, decisions, nextOpen);
  const benchChg = (B[n - 1] / B[0] - 1) * 100;
  const eqChg = (M[n - 1] / o.startCapital - 1) * 100;
  return {
    sub: stale
      ? 'Model book from ' + wdLabel(o.asof) + (fa.model.builtAt ? ' ' + fa.model.builtAt : '') + (fa.failing ? ' — Cycle A has failed since ' + wdLabel(fa.failing.from) : '')
      : 'Model book ' + wdLabel(o.asof) + (fa.model.builtAt ? ' ' + fa.model.builtAt : '') + (acct ? ' · Account (Alpaca ' + (c.env === 'live' ? 'live' : 'paper') + ') ' + (c.data === 'error' ? 'last known ' + (fa.broker?.lastOk ?? '—') : fa.accountAt ?? '—') : ' · Ghost: no broker account yet'),
    eq: usd(M[n - 1]),
    eqSince: spct(eqChg),
    eqCls: tn(eqChg),
    ixic: spct(benchChg),
    ixCls: tn(benchChg),
    sEq: spark(M),
    eqAcct: acct ? 'Account ' + usd(aEq) + ' (' + susd(aEq - M[n - 1]) + ' vs Model)' : 'Account — starts in cash ' + wdLabel(fa.paperStart),
    day: susd(dayChg),
    dayP: spct((dayChg / M[n - 2]) * 100, 2),
    dayCls: tn(dayChg),
    dayWhen: wdLabel(o.asof) + ' close',
    sDay: spark(M.slice(-10)),
    dayAcct: acct && aDay != null ? 'Account ' + susd(aDay) : 'Ghost — no account P&L',
    dd: spct(dd),
    peak: usd(peak, 0),
    mdd: spct(mdd * 100),
    ddW: Math.min((-dd / 25) * 100, 100).toFixed(1),
    exp: f(expPct, 1) + '%',
    cash: usd(c.cash),
    expW: expPct.toFixed(1),
    expAcct: acct && c.accountCash != null ? 'Account ' + f(aExp, 1) + '% invested · cash ' + usd(c.accountCash) : 'EXP_MAX 0.95 · gross cap ' + (c.controls.grossCap == null ? 'off' : c.controls.grossCap + '%'),
    pos: String(rows.length),
    posFree: String(MAX_POSITIONS - rows.length),
    largest: largest ? largest.s + ' ' + f(largest._w, 1) + '%' : '—',
    slots: Array.from({ length: MAX_POSITIONS }, (_, i) => i < rows.length),
    underRev: c.controls.forcedExits.length ? c.controls.forcedExits.length + ' excluded' : positions.filter((h) => h.review).length + ' under review',
    ord: stale ? '0' : String(live.length),
    ordSplit: stale ? 'no new plan' : buys + ' buys · ' + sells + ' sell' + (sells === 1 ? '' : 's') + (blk.length ? ' · ' + blk.length + ' blocked' : ''),
    ordWhen: wdLabel(nextOpen) + ' 09:30 ET',
    ordBlk: blk.length > 0 && !stale,
    ordBlkL: blk.length + ' blocked · ' + blkRules,
    ordNote,
    att,
    attN: String(att.length),
    attCls: att.some((a) => a.tone === 'red') ? 'red' : 'warn',
    rows,
    snapHint: rows.length + ' positions · ' + usd(invested) + ' invested',
  };
}

/* ───────── equity & drawdown chart ───────── */

export type Range = '1W' | '1M' | '3M' | 'YTD' | 'all';
export const RANGES: { l: string; k: Range }[] = [
  { l: '1W', k: '1W' }, { l: '1M', k: '1M' }, { l: '3M', k: '3M' }, { l: 'YTD', k: 'YTD' }, { l: 'Since start', k: 'all' }, { l: 'All', k: 'all' },
];

export interface ChartMarker {
  i: number;
  g: string;
  cls: 'ovr' | 'halt' | 'adp';
  t: string;
}

export interface EquityView {
  dates: string[];
  labels: string[];
  wlabels: string[];
  model: number[];
  account: (number | null)[] | null;
  bench: number[];
  dd: number[];
  marks: ChartMarker[];
  lastM: string;
  lastB: string;
  acctLeg: string;
  acctLegCls: string;
  refDD: number;
  killDD: number;
}

const GLYPH = { adaptation: ['◆', 'adp'], override: ['⚑', 'ovr'], halt: ['■', 'halt'] } as const;

export function selectEquity(c: Ctx, o: OverviewPayload, range: Range): EquityView {
  const acct = c.env !== 'ghost';
  const all = o.equityCurve;
  const N = ({ '1W': 5, '1M': 21 } as Partial<Record<Range, number>>)[range] || all.length;
  const s0 = Math.max(0, all.length - N);
  let pk = 0;
  const DD = all.map((p) => { pk = Math.max(pk, p.model); return (p.model / pk - 1) * 100; }).slice(s0);
  const pts = all.slice(s0);
  const dates = pts.map((p) => p.date);
  const marks: ChartMarker[] = [];
  o.markers.forEach((m: EquityMarker) => {
    const i = dates.indexOf(m.date);
    if (i >= 0) marks.push({ i, g: GLYPH[m.kind][0], cls: GLYPH[m.kind][1], t: m.text });
  });
  const lastA = pts[pts.length - 1].account;
  return {
    dates,
    labels: dates.map(dayLabel),
    wlabels: dates.map(wdLabel),
    model: pts.map((p) => p.model),
    account: acct ? pts.map((p) => p.account) : null,
    bench: pts.map((p) => p.benchmark),
    dd: DD,
    marks,
    lastM: usd(pts[pts.length - 1].model),
    lastB: usd(pts[pts.length - 1].benchmark),
    acctLeg: acct && lastA != null ? 'Account ' + usd(lastA) : 'Account — starts ' + wdLabel(c.facts.paperStart),
    acctLegCls: acct ? '' : 'muted',
    refDD: -16.2,
    killDD: -25,
  };
}

/* ───────── phase ring ───────── */

export function selectPhase(o: OverviewPayload) {
  const C = 2 * Math.PI * 32;
  const p = o.phase;
  return { dash: ((C * p.n) / p.of).toFixed(1) + ' ' + C.toFixed(1), ring: p.n + '/' + p.of, title: p.title, gate: p.gate, dates: p.dates, dec: p.decision };
}

/* ───────── compliance strip ───────── */

export interface StackSeg {
  l: string;
  cls: string;
  c: string;
  w: string;
  p: string;
  t: string;
}

/** Watchlist: within 3 pp of either 30% line and not excluded. */
export const onWatch = (u: { debtPct: number | null; cashPct: number | null; status: string }) =>
  u.debtPct != null && u.cashPct != null && Math.min(30 - u.debtPct, 30 - u.cashPct) < 3 && u.status !== 'Excluded';

export function selectCompStrip(c: Ctx, positions: Position[], universe: UniverseName[] = []) {
  const tot = c.equity;
  const by: Record<string, number> = { A: 0, B: 0, C: 0, F: 0 };
  positions.forEach((h) => { by[sharia(h, c).g] += h.shares * h.last; });
  const col: Record<string, string> = { A: 'var(--g-a)', B: 'var(--g-b)', C: 'var(--g-c)', F: 'var(--g-f)' };
  const stack: StackSeg[] = ['A', 'B', 'C', 'F'].filter((k) => by[k] > 0).map((k) => ({ l: k, cls: 'g' + k, c: col[k], w: ((by[k] / tot) * 100).toFixed(1), p: f((by[k] / tot) * 100, 1) + '%', t: 'Grade ' + k + ' · ' + f((by[k] / tot) * 100, 1) + '% of equity' }));
  stack.push({ l: '$', cls: '', c: 'var(--bg-4)', w: ((c.cash / tot) * 100).toFixed(1), p: f((c.cash / tot) * 100, 1) + '%', t: 'Cash' });
  const rev = positions.filter((h) => h.review && !c.controls.forcedExits.includes(h.symbol));
  const watch = universe.filter(onWatch).length;
  return {
    stack,
    stackL: stack.map((s) => (s.l === '$' ? 'cash ' : s.l + ' ') + s.p).join(' · '),
    rev: rev.length ? rev.length + ' · ' + rev.map((h) => h.symbol).join(', ') : '0',
    watch: watch + (watch === 1 ? ' name' : ' names'),
    fresh: 'screened ' + wdLabel(c.facts.screen.last),
    next: wdLabel(c.facts.screen.next) + ' ' + c.facts.screen.next.slice(0, 4),
  };
}

/** The Overview's holdings snapshot uses the full Model rows. */
export type { HoldingRow };
