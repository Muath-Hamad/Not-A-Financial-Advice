// Orders screen: pending for the next open, history with slippage and
// lifecycle, and closed round trips. Ported from vmOrders, vmPending,
// pendView, vmHistory and vmRT.

import type { HistOrder, Intent as OrderIntent, PendingPayload, Position, RoundTrip, Side } from '@/api/types';
import { band, bandL, f, hbars, spct, susd, tn, usd } from '@/lib/format';
import { compact, dayLabel, wdLabel } from '@/lib/dates';
import { lcHist, lcPending, pendingRows, type LcStep, type PendingRow } from './core';
import type { Ctx } from './ctx';

export const ORDERS_SUB = 'Market-on-open orders (opg) · Cycle A ledgers at 17:05 ET · submit sends at 19:15 ET · fills at the 09:30 open · Cycle B reconciles at 09:50';

/* ───────── pending ───────── */

export interface PendView {
  id: string;
  s: string;
  n: string;
  sideCls: 'buy' | 'sell';
  sideL: string;
  qty: string;
  amt: string;
  ref: string;
  est: string;
  why: string;
  srcL: string;
  srcCls: string;
  grOk: boolean;
  gr: string;
  grNote: string;
  lc: LcStep[];
  state: string;
  sc: string;
  cid: string;
  rowCls: string;
  canCancel: boolean;
}

export function pendView(o: PendingRow, c: Ctx): PendView {
  return {
    id: o.id,
    s: o.symbol,
    n: o.name,
    sideCls: o.side === 'BUY' ? 'buy' : 'sell',
    sideL: (o.side === 'BUY' ? '↑ ' : '↓ ') + o.side,
    qty: o.qtyLabel,
    amt: o.amountLabel || '',
    ref: usd(o.refClose),
    est: usd(o.estValue),
    why: o.reason,
    srcL: { agent: 'Agent', forced: 'Forced exit · Sharia', manual: 'Manual · owner' }[o.source],
    srcCls: { agent: '', forced: 'warn', manual: 'info' }[o.source],
    grOk: !o.guardrail,
    gr: o.guardrail || '',
    grNote: o.guardrailNote || '',
    lc: lcPending(o, c),
    state: o.state,
    sc: o.sc,
    cid: o.clientOrderId,
    rowCls: o.live ? '' : 'mut',
    canCancel: o.source === 'manual' && c.role === 'owner' && !o.flatten,
  };
}

export function selectPending(c: Ctx, p: PendingPayload, positions: Position[]) {
  const rows = pendingRows(p.intents, positions, c);
  const T = c.trading;
  const g = c.env === 'ghost';
  const stale = c.data === 'stale';
  const live = rows.filter((o) => o.live);
  const buys = live.filter((o) => o.side === 'BUY').reduce((a, o) => a + o.estValue, 0);
  const sells = live.filter((o) => o.side === 'SELL').reduce((a, o) => a + o.estValue, 0);
  let status = g ? 'Planned · ghost rehearsal' : 'Planned · awaiting 19:15 submit';
  let stCls = 'blue';
  if (T === 'held') { status = 'Held · approval mode'; stCls = 'amber pulse'; }
  if (T === 'halted') { status = 'Halted · submit blocked'; stCls = 'red'; }
  if (T === 'stopped') { status = 'Stopped · kill switch'; stCls = 'red'; }
  if (c.released) { status = 'Submitted · accepted 19:31 ET'; stCls = 'green'; }
  if (stale) { status = 'No plan · Cycle A failing'; stCls = 'red'; }
  const net = buys - sells;
  return {
    nextOpen: wdLabel(p.nextOpen) + ' 09:30 ET',
    window: 'Submit 19:15 ET (retry 19:45) · manual submit until 09:28 ET',
    status,
    stCls,
    held: T === 'held',
    holdWhy: 'approval mode (first paper week)',
    hint: rows.length + ' intents · ' + live.length + ' to send · ' + (rows.length - live.length) + ' blocked or canceled',
    none: rows.length === 0,
    noneH: stale ? 'No new plan since ' + wdLabel(c.asof) : 'No orders for the next open',
    noneP: stale
      ? 'Cycle A has failed 4 sessions in a row (data gate: coverage at asof 0.6% < 95%). Nothing trades on partial data; the day is skipped, never guessed.'
      : 'Cycle A ledgered no intents for this session.',
    noneAct: stale,
    rows: rows.map((o) => pendView(o, c)),
    buys: usd(buys),
    sells: usd(sells),
    net: net >= 0 ? usd(net) : usd(-net) + ' freed',
    turn: f(((buys + sells) / c.equity) * 100, 1) + '%',
    left: usd(c.cash - net),
    count: rows.length,
  };
}

/* ───────── history ───────── */

export interface HistRow {
  id: string;
  s: string;
  side: Side;
  sideCls: 'buy' | 'sell';
  dd: string;
  fd: string;
  q: string;
  dc: string;
  op: string;
  fp: string;
  slip: string;
  slipCls: string;
  sf: string;
  val: string;
  fee: string;
  rp: string;
  rpCls: string;
  days: string;
  st: string;
  hasAdj: boolean;
  adjS: string;
  adj: string;
  why: string;
  cid: string;
  file: string;
  lc: LcStep[];
  json: string;
}

export type SideFilter = 'all' | Side;

const sgn = (v: number) => (v > 0.05 ? '+' : v < -0.05 ? '−' : '') + f(v, 1);

/** Slippage vs the official open, signed by side: + is a cost. */
export function slippageBps(side: Side, open: number, fill: number): number {
  return side === 'BUY' ? ((fill - open) / open) * 1e4 : ((open - fill) / open) * 1e4;
}

export function selectHistory(c: Ctx, h: { orders: HistOrder[]; total: number; feesSinceStart: number; since: string }, side: SideFilter) {
  const { orders, total, feesSinceStart, since } = h;
  const g = c.env === 'ghost';
  let fees = 0;
  const rows: HistRow[] = orders.filter((o) => side === 'all' || o.side === side).map((o) => {
    const fp = g ? o.officialOpen : o.fillPrice;
    const q = g ? o.shares : o.accountShares || o.shares;
    const slip = slippageBps(o.side, o.officialOpen, fp);
    const sf = o.side === 'BUY' ? ((fp - o.decisionClose) / o.decisionClose) * 1e4 : ((o.decisionClose - fp) / o.decisionClose) * 1e4;
    const cid = 'trend-' + compact(o.decisionDate) + '-' + o.symbol + '-' + (o.side === 'BUY' ? 'B' : 'S') + '1';
    fees += g ? 0 : o.fees;
    const adj = !!(o.accountShares && !g);
    return {
      id: o.id, s: o.symbol, side: o.side, sideCls: o.side === 'BUY' ? 'buy' : 'sell',
      dd: wdLabel(o.decisionDate), fd: wdLabel(o.fillDate), q: String(q),
      dc: usd(o.decisionClose), op: usd(o.officialOpen), fp: usd(fp),
      slip: sgn(slip), slipCls: Math.abs(slip) > 10 ? 'danger' : '', sf: sgn(sf),
      val: usd(q * fp), fee: usd(g ? 0 : o.fees),
      rp: o.realized == null ? '—' : susd(o.realized), rpCls: o.realized == null ? 'muted' : tn(o.realized),
      days: o.heldDays == null ? '—' : String(o.heldDays),
      st: 'Reconciled', hasAdj: adj, adjS: adj ? 'adjusted ' + o.shares + ' → ' + o.accountShares : '',
      adj: 'Adjusted at submit: the twin bought ' + o.shares + ' sh; buys are trimmed to the cash the night’s sells free (F6), so the account bought ' + o.accountShares + '. Drift alert A-38.',
      why: o.reason, cid, file: o.decisionDate, lc: lcHist(o, !g),
      json: JSON.stringify({ client_order_id: cid, symbol: o.symbol, side: o.side.toLowerCase(), qty: q, type: 'market', time_in_force: 'opg', decision_close: o.decisionClose, official_open: o.officialOpen, filled_avg_price: fp, slippage_bps: +slip.toFixed(1), shortfall_bps: +sf.toFixed(1), fees: g ? 0 : o.fees, status: 'reconciled' }, null, 2),
    };
  });
  return {
    hint: 'latest ' + rows.length + ' of ' + total + ' orders · since ' + wdLabel(since) + (g ? ' · ghost fills at the official open' : ''),
    rows,
    foot: 'Fees on these orders ' + usd(fees) + ' · since start ' + susd(-feesSinceStart) + ' · 0 rejected · 0 missed',
  };
}

/* ───────── round trips ───────── */

const REASONS: [RoundTrip['exitReason'], string][] = [['stop', 'Initial stop'], ['trail', 'Trailing stop'], ['rank', 'Rank decay'], ['time', 'Time stop'], ['sma', 'SMA200'], ['forced', 'Forced (Sharia)'], ['manual', 'Manual']];
const REASON_L = Object.fromEntries(REASONS) as Record<RoundTrip['exitReason'], string>;

export function selectRoundTrips(trips: RoundTrip[], fees: number) {
  const wins = trips.filter((r) => r.pnl > 0);
  const losses = trips.filter((r) => r.pnl < 0);
  const gw = wins.reduce((a, r) => a + r.pnl, 0);
  const gl = losses.reduce((a, r) => a + r.pnl, 0);
  const byR = REASONS.map(([k, l]) => {
    const rs = trips.filter((r) => r.exitReason === k);
    return { l, n: rs.length + (rs.length === 1 ? ' trip' : ' trips'), v: rs.reduce((a, r) => a + r.pnl, 0) };
  });
  const n = trips.length || 1;
  return {
    win: f((wins.length / n) * 100, 1) + '%',
    winN: wins.length + ' wins of ' + trips.length + ' round trips',
    avgW: wins.length ? susd(gw / wins.length) : '—',
    avgL: losses.length ? susd(gl / losses.length) : '—',
    payoff: wins.length && losses.length ? f(gw / wins.length / Math.abs(gl / losses.length), 2) : '—',
    pf: gl ? f(gw / Math.abs(gl), 2) : '—',
    tot: susd(gw + gl - fees),
    totCls: tn(gw + gl - fees),
    totN: 'gross ' + susd(gw + gl) + ' · fees ' + susd(-fees),
    byR: hbars(byR),
    rows: trips.map((r) => ({
      s: r.symbol, e: dayLabel(r.entryDate), x: dayLabel(r.exitDate), d: String(r.days),
      ep: usd(r.entryPrice), xp: usd(r.exitPrice), pnl: susd(r.pnl), pct: spct((r.exitPrice / r.entryPrice - 1) * 100), cls: tn(r.pnl),
      r: REASON_L[r.exitReason], c: String(r.confAtEntry), band: band(r.confAtEntry), bandL: bandL(r.confAtEntry),
    })),
    count: trips.length,
  };
}

export function pendingCount(c: Ctx, intents: OrderIntent[], positions: Position[]): number {
  return pendingRows(intents, positions, c).length;
}
