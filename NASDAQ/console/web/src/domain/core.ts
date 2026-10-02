// Shared domain selectors, ported from the prototype's Component class
// (pill, tonight, sharia, confOf, exitOf, pendingRows, lcPending, lcHist,
// hRows). Pure functions of API payloads plus the system context.

import type { Alert, HistOrder, Intent, Position } from '@/api/types';
import { band, bandL, f, spct, susd, tn, usd, type Band, type Tone } from '@/lib/format';
import { compact, dow, hm, wdLabel } from '@/lib/dates';
import type { Ctx } from './ctx';

/* ───────── trading state ───────── */

export interface Pill {
  cls: string;
  l: string;
  s: string;
}

export function pill(c: Ctx): Pill {
  switch (c.trading) {
    case 'paused': return { cls: 'amber', l: 'Entries paused', s: 'Paused' };
    case 'held': return { cls: 'amber pulse', l: 'Night held · approval needed', s: 'Held' };
    case 'halted': return { cls: 'red', l: 'Halted · reconciliation break', s: 'Halted' };
    case 'stopped': return { cls: 'red', l: 'Stopped · kill', s: 'Stopped' };
    default: return { cls: 'green', l: 'Running', s: 'Running' };
  }
}

export interface TimelineStep {
  l: string;
  time: string;
  cls: '' | 'done' | 'fail' | 'run' | 'held' | 'skip';
  g: string;
  cd: string;
  ms: string;
  title: string;
  mcls: 'pos' | 'danger' | 'warn' | 'muted';
}

/** Tonight's schedule in the top bar: Cycle A → Submit → Open → Cycle B. */
export function tonight(c: Ctx): TimelineStep[] {
  const S = (l: string, time: string, cls: TimelineStep['cls'], g: string, cd: string, ms: string, title?: string): TimelineStep => ({
    l, time, cls, g, cd, ms,
    title: title || l + ' ' + time,
    mcls: cls === 'done' ? 'pos' : cls === 'fail' ? 'danger' : cls === 'run' || cls === 'held' ? 'warn' : 'muted',
  });
  const fa = c.facts;
  const la = fa.lastCycleA;
  const openDay = dow(fa.nextOpen);
  const A = S('Cycle A', '17:05', 'done', '✓', '', 'A', 'Cycle A 17:05 ET — ok' + (la?.durationS ? ' in ' + Math.round(la.durationS) + ' s' : ''));
  const T = c.trading;
  if (c.data === 'stale') return [S('Cycle A', '17:05', 'fail', '✗', '', 'A', 'Cycle A 17:05 ET — failed: ' + (fa.failing?.reason.split(':')[0].toLowerCase() ?? 'see Health')), S('Submit', '19:15', 'skip', '–', '', 'Submit', 'Submit 19:15 ET — nothing to send'), S('Open', openDay + ' 09:30', '', '·', '', 'Open'), S('Cycle B', '09:50', '', '·', '', 'B')];
  if (T === 'halted') return [S('Cycle A', dow(fa.model.asof) + ' 17:05', 'done', '✓', '', 'A'), S('Submit', '19:15', 'done', '✓', '', 'Submit'), S('Open', '09:30', 'done', '✓', '', 'Open'), S('Cycle B', '09:50', 'fail', '✗', '', 'B', 'Cycle B 09:50 ET — reconciliation break')];
  if (T === 'held') return [A, S('Submit', '19:15', 'held', '‖', 'held', 'Submit', 'Submit 19:15 ET — held for approval'), S('Open', openDay + ' 09:30', '', '·', '', 'Open'), S('Cycle B', '09:50', '', '·', '', 'B')];
  if (T === 'stopped') return [A, S('Submit', '19:15', 'skip', '–', '', 'Submit', 'Submit — skipped: kill switch'), S('Open', openDay + ' 09:30', 'skip', '–', '', 'Open'), S('Cycle B', '09:50', '', '·', '', 'B')];
  if (c.released || fa.submitInMin == null) return [A, S('Submit', c.released ? '19:31' : '19:15', 'done', '✓', '', 'Submit', c.released ? 'Submit — released 19:31 ET' : 'Submit 19:15 ET'), S('Open', openDay + ' 09:30', 'run', '◷', hm(fa.openInMin), 'Open'), S('Cycle B', '09:50', '', '·', '', 'B')];
  return [A, S('Submit', '19:15', 'run', '◷', hm(fa.submitInMin), 'Submit', 'Submit 19:15 ET — in ' + hm(fa.submitInMin)), S('Open', openDay + ' 09:30', '', '·', '', 'Open'), S('Cycle B', '09:50', '', '·', '', 'B')];
}

/* ───────── Sharia (docs/08 §5) ───────── */

export interface RatioGauge {
  v: string;
  w: string;
  head: string;
  hCls: 'danger' | 'warn' | 'dim';
  cls: 'neg' | 'warn' | 'ok';
}

export interface ShariaCard {
  status: string;
  stCls: 'pos' | 'warn' | 'danger';
  g: 'A' | 'B' | 'C' | 'F';
  gCls: string;
  why: string;
  short: 'Compliant' | 'Under review' | 'Excluded';
  debt: RatioGauge;
  cash: RatioGauge;
  biz: string;
  bizCls: string;
  flag: string;
  flagCls: string;
  ruling: string;
  screened: string;
  purif: string;
}

function ratio(v: number | null): RatioGauge {
  if (v == null) return { v: '—', w: '0', head: 'Not available – licensed data pending', hCls: 'dim', cls: 'ok' };
  const hd = 30 - v;
  return {
    v: f(v, 1) + '%',
    w: Math.min((v / 40) * 100, 100).toFixed(1),
    head: f(hd, 1) + ' pp headroom',
    hCls: hd < 3 ? 'danger' : hd < 10 ? 'warn' : 'dim',
    cls: v >= 30 ? 'neg' : hd < 10 ? 'warn' : 'ok',
  };
}

/** Sharia grade (docs/08 §5): A ≥ 10 pp headroom on both ratios and no flag;
 *  B under 10 pp; C review-flagged, under 3 pp or ratios missing; F excluded or failing. */
export function gradeOf(debt: number | null, cash: number | null, review: boolean, excluded: boolean): ShariaCard['g'] {
  if (excluded) return 'F';
  if (debt == null || cash == null) return 'C';
  const head = Math.min(30 - debt, 30 - cash);
  if (head < 0) return 'F';
  if (review || head < 3) return 'C';
  if (head < 10) return 'B';
  return 'A';
}

const year = (iso: string) => iso.slice(0, 4);

export function sharia(h: Position, c: Ctx): ShariaCard {
  const forced = c.controls.forcedExits.includes(h.symbol);
  const review = !!h.review && !forced;
  const g = gradeOf(h.debtPct, h.cashPct, review, forced);
  let status = 'Compliant';
  let stCls: ShariaCard['stCls'] = 'pos';
  let why = g === 'A'
    ? 'Passes every layer · both ratios ≥ 10 pp headroom · no review flag'
    : g === 'B' ? 'Passes every layer, but a ratio is within 10 pp of the 30% line' : 'Passes, but a ratio is within 3 pp of the 30% line or missing';
  if (review) {
    status = 'Under review'; stCls = 'warn';
    why = 'Passes the ratios, but review-flagged: owner ruling pending (D1)';
  }
  if (forced) {
    status = 'Excluded — exit queued'; stCls = 'danger';
    why = 'Excluded · forced exit at the next open';
  }
  const d = h.nextDividend;
  const scr = c.facts.screen;
  const on = h.screenedOn ?? scr.last;
  return {
    status, stCls, g, gCls: 'g' + g, why,
    short: review ? 'Under review' : forced ? 'Excluded' : 'Compliant',
    debt: ratio(h.debtPct),
    cash: ratio(h.cashPct),
    biz: h.industry + (review && h.review ? ' · flag: "' + h.review.keyword + '"' : ' · no impermissible keywords · pass'),
    bizCls: review ? 'warn' : '',
    flag: review ? 'Flagged — ruling pending' : forced ? 'Excluded' : 'None',
    flagCls: review ? 'warn' : forced ? 'danger' : 'dim',
    ruling: review ? 'Due ' + wdLabel(c.facts.d1Due) + ' ' + year(c.facts.d1Due) + ' (D1)' : forced ? 'Excluded · forced exit queued' : '—',
    screened: wdLabel(on) + ' ' + year(on) + ' · next ' + wdLabel(scr.next) + ' ' + year(scr.next),
    purif: d
      ? 'Next dividend ~' + usd(d.perShare * d.shares) + ' gross (' + d.shares + ' × $' + f(d.perShare, 3) + ', pay ' + wdLabel(d.payDate) + ') · rate pending'
      : 'No dividend received · nothing due',
  };
}

/* ───────── confidence (docs/08 §6) ───────── */

export const CONF_WEIGHTS = [40, 30, 20, 10] as const;

export interface ConfView {
  c: number[];
  tot: number;
  band: Band;
  bandL: string;
  segs: { w: number; f: number }[];
  title: string;
}

/** null until the insights step (M3) ledgers confidence for this holding. */
export function confOf(h: Position, c: Ctx): ConfView | null {
  const k = h.confidence;
  if (!k) return null;
  const sub = [k.signal, k.riskRoom, k.regime, c.data === 'stale' ? 15 : k.data];
  const tot = Math.round(sub[0] * 0.4 + sub[1] * 0.3 + sub[2] * 0.2 + sub[3] * 0.1);
  return {
    c: sub,
    tot,
    band: band(tot),
    bandL: bandL(tot),
    segs: sub.map((v, i) => ({ w: CONF_WEIGHTS[i], f: v })),
    title: 'Signal ' + sub[0] + ' · Risk room ' + sub[1] + ' · Regime ' + sub[2] + ' · Data ' + sub[3] + ' — model conviction, not a forecast',
  };
}

/* ───────── nearest exit ───────── */

export interface ExitView {
  k: string;
  p: string;
  d: string;
  cls: string;
  near: boolean;
  full: string;
  stopK: string;
  stopP: number | null;
  dist: number | null;
}

export function stopOf(h: Position): { stopK: string; stopP: number | null; dist: number | null } {
  if (h.initialStop == null || h.atr == null) return { stopK: 'Nearest exit', stopP: null, dist: null };
  const trailing = h.trailingStop != null && h.trailingStop > h.initialStop;
  const stopP = trailing ? (h.trailingStop as number) : h.initialStop;
  return { stopK: trailing ? 'Trailing stop' : 'Initial stop', stopP, dist: (h.last - stopP) / h.atr };
}

export const STOPS_PENDING = 'Stop levels come from the insights step (milestone M3)';

export function exitOf(h: Position): ExitView {
  const s = stopOf(h);
  if (h.rankExit) {
    return { ...s, k: 'Rank exit', p: h.rank != null ? 'rank ' + h.rank + ' > 30' : 'out of the top 30', d: 'triggered · sells at the open', cls: 'warn', near: true, full: 'Rank exit — momentum rank is past the exit threshold of 30; sell queued for the open' };
  }
  if (s.stopP == null || s.dist == null) {
    return { ...s, k: 'Nearest exit', p: '—', d: 'awaiting insights (M3)', cls: 'muted', near: h.heldSessions >= 28, full: STOPS_PENDING + ' · time stop after 35 sessions (' + h.heldSessions + ' held)' };
  }
  return {
    ...s,
    k: s.stopK,
    p: usd(s.stopP),
    d: f(s.dist, 1) + ' ATR away',
    cls: s.dist < 1 ? 'warn' : '',
    near: s.dist < 1.5 || h.heldSessions >= 28,
    full: s.stopK + ' ' + usd(s.stopP) + ' · ' + f(s.dist, 1) + ' ATR away (ATR ' + usd(h.atr as number) + ')',
  };
}

/* ───────── pending orders for the next open ───────── */

export type StateCls = 'info' | 'danger' | 'warn' | 'pos';

export interface PendingRow extends Intent {
  live: boolean;
  state: string;
  sc: StateCls;
}

/**
 * Agent intents plus the owner's forced exits, manual trims and a queued
 * flatten, each with its guardrail result and lifecycle state.
 */
export function pendingRows(intents: Intent[], positions: Position[], c: Ctx): PendingRow[] {
  if (c.data === 'stale' || c.data === 'empty' || c.data === 'loading') return [];
  const ctl = c.controls;
  const T = c.trading;
  const ymd = compact(c.asof);
  const rows: Intent[] = intents.map((o) => ({ ...o }));
  const find = (s: string) => positions.find((x) => x.symbol === s);
  ctl.forcedExits.forEach((sym) => {
    const h = find(sym);
    if (h) rows.push({ id: 'f-' + sym, symbol: sym, name: h.name, side: 'SELL', shares: h.shares, qtyLabel: h.shares + ' sh (all)', amountLabel: '', refClose: h.last, estValue: h.shares * h.last, reason: 'Owner exclusion (Sharia ruling) — full exit at the next open', source: 'forced', guardrail: null, guardrailNote: '', clientOrderId: 'console-' + ymd + '-' + sym + '-X1' });
  });
  ctl.manualOrders.forEach((mo) => {
    const h = find(mo.symbol);
    if (h) rows.push({ id: 'm-' + mo.symbol, symbol: mo.symbol, name: h.name, side: 'SELL', shares: mo.shares, qtyLabel: mo.shares + ' sh (' + mo.pct + '%)', amountLabel: '', refClose: h.last, estValue: mo.shares * h.last, reason: 'Manual trim by the owner', source: 'manual', guardrail: null, guardrailNote: '', clientOrderId: 'console-' + ymd + '-' + mo.symbol + '-M1' });
  });
  if (c.flatten) {
    positions.forEach((h) => {
      if (!rows.some((r) => r.symbol === h.symbol && r.side === 'SELL' && r.source !== 'agent')) {
        rows.push({ id: 'x-' + h.symbol, symbol: h.symbol, name: h.name, side: 'SELL', shares: h.shares, qtyLabel: h.shares + ' sh (all)', amountLabel: '', refClose: h.last, estValue: h.shares * h.last, reason: 'Stop & flatten — sell everything at the open', source: 'manual', guardrail: null, guardrailNote: '', clientOrderId: 'console-' + ymd + '-' + h.symbol + '-F1', flatten: true });
      }
    });
  }
  return rows.map((o) => {
    let gr = o.guardrail || null;
    let note = o.guardrailNote || '';
    let live = true;
    let state = 'Ledgered · awaiting 19:15 submit';
    let sc: StateCls = 'info';
    if (!gr && T === 'paused' && o.side === 'BUY' && o.source === 'agent') { gr = 'pause_entries'; note = 'entries paused by the owner'; }
    if (!gr && ctl.lockedSymbols.includes(o.symbol) && o.source === 'agent') { gr = 'locked'; note = 'owner lock on ' + o.symbol; }
    if (!gr && o.side === 'BUY' && ctl.excludedSymbols.includes(o.symbol)) { gr = 'excluded_symbols'; note = 'name excluded'; }
    if (!gr && o.side === 'BUY' && ctl.grossCap != null && ctl.grossCap < 95) { gr = 'gross_cap'; note = 'exposure 94.8% > cap ' + ctl.grossCap + '%'; }
    if (gr) { live = false; state = 'Blocked'; sc = 'danger'; }
    else if (T === 'stopped' && !o.flatten && !(o.source !== 'agent' && c.flatten)) { live = false; state = 'Canceled · kill'; sc = 'danger'; }
    else if (T === 'held') { state = 'Held · approval'; sc = 'warn'; }
    else if (T === 'halted') { state = 'Held · halt'; sc = 'danger'; }
    else if (c.released) { state = 'Accepted 19:31:06'; sc = 'pos'; }
    else if (c.env === 'ghost') state = 'Ledgered · rehearsal 19:15';
    return { ...o, guardrail: gr, guardrailNote: note, live, state, sc };
  });
}

/* ───────── order lifecycle (docs/08 §4.2) ───────── */

export interface LcStep {
  l: string;
  t: string;
  c: 'done' | 'cur' | 'fail' | 'todo';
  g: string;
  m: '' | 'd' | 'c' | 'f';
}

const lc = (l: string, t: string, c: LcStep['c']): LcStep => ({ l, t, c, g: c === 'done' ? '✓' : c === 'fail' ? '✕' : '', m: c === 'done' ? 'd' : c === 'cur' ? 'c' : c === 'fail' ? 'f' : '' });

export function lcPending(o: PendingRow, c: Ctx): LcStep[] {
  const T = c.trading;
  const t0 = o.source === 'agent' ? '17:05:38' : '18:04';
  if (o.guardrail) return [lc('Intent', t0, 'done'), lc('Guardrails', '✕ ' + o.guardrail, 'fail'), lc('Planned', '—', 'todo'), lc('Accepted', '—', 'todo'), lc('Filled', '—', 'todo'), lc('Reconciled', '—', 'todo')];
  if (!o.live) return [lc('Intent', t0, 'done'), lc('Guardrails', '✓', 'done'), lc('Canceled', 'kill switch', 'fail'), lc('Accepted', '—', 'todo'), lc('Filled', '—', 'todo'), lc('Reconciled', '—', 'todo')];
  if (c.released) return [lc('Intent', t0, 'done'), lc('Guardrails', '✓', 'done'), lc('Released', '19:31', 'done'), lc('Accepted', '19:31:06', 'done'), lc('Filled', 'Mon 09:30', 'cur'), lc('Reconciled', '09:50', 'todo')];
  if (T === 'held') return [lc('Intent', t0, 'done'), lc('Guardrails', '✓', 'done'), lc('Held', '19:15 approval', 'cur'), lc('Accepted', '—', 'todo'), lc('Filled', 'Mon 09:30', 'todo'), lc('Reconciled', '09:50', 'todo')];
  if (T === 'halted') return [lc('Intent', t0, 'done'), lc('Guardrails', '✓', 'done'), lc('Held', 'halt.json', 'fail'), lc('Accepted', '—', 'todo'), lc('Filled', '—', 'todo'), lc('Reconciled', '—', 'todo')];
  return [lc('Intent', t0, 'done'), lc('Guardrails', '✓', 'done'), lc('Planned', '19:15', 'cur'), lc('Accepted', '—', 'todo'), lc('Filled', 'Mon 09:30', 'todo'), lc('Reconciled', '09:50', 'todo')];
}

export function lcHist(o: HistOrder, acct: boolean): LcStep[] {
  const dd = wdLabel(o.decisionDate).replace(/^\w+ /, '');
  const fd = wdLabel(o.fillDate).replace(/^\w+ /, '');
  const adj = !!(o.accountShares && acct);
  return [
    lc('Intent', dd + ' 17:05:38', 'done'),
    lc('Guardrails', '✓', 'done'),
    lc(adj ? 'Adjusted' : 'Planned', adj ? o.shares + ' → ' + o.accountShares + ' sh' : '19:15:02', 'done'),
    lc(acct ? 'Accepted' : 'Rehearsed', '19:15:04', 'done'),
    lc('Filled', fd + ' 09:30:01', 'done'),
    lc('Reconciled', '09:50:47', 'done'),
  ];
}

/* ───────── alerts ───────── */

/** Open first, P1 before P2, then acknowledged, then resolved. */
export function sortAlerts(list: Alert[]): Alert[] {
  const rank = (a: Alert) => (a.status === 'open' ? 0 : a.status === 'acknowledged' ? 2 : 4) + (a.priority === 'P1' ? 0 : 1);
  return [...list].sort((x, y) => rank(x) - rank(y));
}

export const openAlerts = (list: Alert[]) => list.filter((a) => a.status === 'open');

/* ───────── books ───────── */

export function acctShares(h: Position): number {
  return h.account ? h.account.shares : h.shares;
}

export function acctEquity(positions: Position[], c: Ctx): number {
  return positions.reduce((a, h) => a + acctShares(h) * h.last, 0) + (c.accountCash ?? 0);
}

export interface HoldingRow {
  s: string;
  n: string;
  sec: string;
  locked: boolean;
  sh: string;
  avg: string;
  last: string;
  day: string;
  dayCls: Tone;
  val: string;
  w: string;
  wb: string;
  u: string;
  uP: string;
  uCls: Tone;
  rz: string;
  held: string;
  heldB: string;
  heldCls: string;
  exK: string;
  exP: string;
  exD: string;
  exCls: string;
  c: string;
  band: Band | 'none';
  bandL: string;
  segs: { w: number; f: number }[];
  cT: string;
  g: string;
  gCls: string;
  stat: string;
  pend: string;
  pendS: string;
  pCls: string;
  _w: number;
  _u: number;
  _val: number;
  _c: number | null;
  _g: string;
  _sec: string;
  _near: boolean;
}

export function holdingRows(positions: Position[], intents: Intent[], c: Ctx, book: 'model' | 'account'): HoldingRow[] {
  const acct = book === 'account';
  const pend = pendingRows(intents, positions, c);
  const eq = acct ? acctEquity(positions, c) : c.equity;
  return positions.map((h) => {
    const sh = acct ? acctShares(h) : h.shares;
    const avg = acct && h.account ? h.account.avgCost : h.avgCost;
    const val = sh * h.last;
    const u = (h.last - avg) * sh;
    const up = (h.last / avg - 1) * 100;
    const w = (val / eq) * 100;
    const cv = confOf(h, c);
    const sv = sharia(h, c);
    const ex = exitOf(h);
    const po = pend.filter((o) => o.symbol === h.symbol && o.live);
    const locked = c.controls.lockedSymbols.includes(h.symbol);
    const pendL = po.length
      ? po.map((o) => o.side + ' ' + o.shares + ' @ open' + (o.source === 'forced' ? ' (forced)' : o.source === 'manual' ? ' (manual)' : '')).join(' · ')
      : locked ? 'Locked — agent skips' : '—';
    return {
      s: h.symbol, n: h.name, sec: h.sector, locked,
      sh: String(sh), avg: usd(avg), last: usd(h.last), day: h.dayPct == null ? '' : spct(h.dayPct, 2), dayCls: h.dayPct == null ? 'dim' : tn(h.dayPct),
      val: usd(val), w: f(w, 1) + '%', wb: Math.min((w / 20) * 100, 100).toFixed(1),
      u: susd(u), uP: spct(up, 1), uCls: tn(u), rz: '$0.00',
      held: h.heldSessions + ' / 35', heldB: ((h.heldSessions / 35) * 100).toFixed(1), heldCls: h.heldSessions >= 28 ? 'warn' : '',
      exK: ex.k, exP: ex.p, exD: ex.d, exCls: ex.cls,
      c: cv ? String(cv.tot) : '—', band: cv ? cv.band : 'none', bandL: cv ? cv.bandL : 'Pending', segs: cv ? cv.segs : [],
      cT: cv ? cv.title : 'Confidence is computed by the insights step (milestone M3) — not available yet',
      g: sv.g, gCls: sv.gCls, stat: sv.short,
      pend: pendL,
      pendS: po.length ? po[0].side + ' @ open' : locked ? 'Locked' : '',
      pCls: po.length ? (po.some((o) => o.source !== 'agent') ? 'warn' : 'info') : locked ? 'warn' : 'muted',
      _w: w, _u: u, _val: val, _c: cv ? cv.tot : null, _g: sv.g, _sec: h.sector, _near: ex.near,
    };
  });
}
