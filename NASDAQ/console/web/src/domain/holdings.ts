// Holdings screen and the holding detail drawer. Ported from vmHoldings,
// vmSide, vmDrawer, vmPrice, vmConf and vmShariaD.

import type { HistOrder, HoldingDetailPayload, Intent as OrderIntent, Position, RoundTrip } from '@/api/types';
import { band, f, path, spct, susd, tn, usd, type Band } from '@/lib/format';
import { dayLabel, wdLabel } from '@/lib/dates';
import {
  acctEquity, acctShares, confOf, exitOf, holdingRows, lcHist, lcPending, pendingRows, sharia,
  type HoldingRow, type LcStep, type ShariaCard,
} from './core';
import type { Ctx } from './ctx';

export type Book = 'model' | 'account' | 'side';

export interface HoldingsFilters {
  q: string;
  sector: string;
  grade: string;
  band: string;
  sign: 'all' | 'pos' | 'neg';
  near: boolean;
}

export const NO_FILTERS: HoldingsFilters = { q: '', sector: 'all', grade: 'all', band: 'all', sign: 'all', near: false };

export interface HoldingsColumns {
  realized: boolean;
  held: boolean;
  pending: boolean;
}

export interface HoldingsView {
  sub: string;
  title: string;
  tag: string;
  tagCls: string;
  count: string;
  frCls: string;
  frL: string;
  errNote: boolean;
  errText: string;
  noAcct: boolean;
  main: boolean;
  side: boolean;
  cols: string;
  rows: HoldingRow[];
  none: boolean;
  n: string;
  tMV: string;
  tW: string;
  tU: string;
  tUCls: string;
  tR: string;
  tRCls: string;
  cash: string;
  eq: string;
  tC: string;
  tBand: Band | 'none';
  tGrades: string;
  sectors: string[];
}

export function filterRows(all: HoldingRow[], fl: HoldingsFilters): HoldingRow[] {
  const q = fl.q.trim().toLowerCase();
  return all.filter((r) =>
    (!q || r.s.toLowerCase().includes(q) || r.n.toLowerCase().includes(q))
    && (fl.sector === 'all' || r._sec === fl.sector)
    && (fl.grade === 'all' || r._g === fl.grade)
    && (fl.band === 'all' || r.band === fl.band)
    && (fl.sign === 'all' || (fl.sign === 'pos' ? r._u > 0 : r._u < 0))
    && (!fl.near || r._near));
}

export function holdingsColumns(c: HoldingsColumns): string {
  const cols = ['170px', '64px', '84px', '88px', '96px', '140px', '112px'];
  if (c.realized) cols.push('84px');
  if (c.held) cols.push('120px');
  cols.push('210px', '150px', '140px');
  if (c.pending) cols.push('180px');
  cols.push('48px');
  return cols.join(' ');
}

export function selectHoldings(c: Ctx, positions: Position[], intents: OrderIntent[], book: Book, fl: HoldingsFilters, colsOn: HoldingsColumns, modelFresh: { cls: string; l: string }): HoldingsView {
  const acct = c.env !== 'ghost';
  const err = c.data === 'error';
  const isA = book === 'account';
  const isS = book === 'side';
  const all = isS ? [] : holdingRows(positions, intents, c, isA ? 'account' : 'model');
  const rows = filterRows(all, fl);
  const eq = isA ? acctEquity(positions, c) : c.equity;
  const mv = all.reduce((a, r) => a + r._val, 0);
  const tu = all.reduce((a, r) => a + r._u, 0);
  const rated = all.filter((r) => r._c != null);
  const rv = rated.reduce((a, r) => a + r._val, 0);
  const wc = rated.length ? Math.round(rated.reduce((a, r) => a + r._val * (r._c as number), 0) / Math.max(rv, 1)) : null;
  const grades: Record<string, number> = {};
  all.forEach((r) => { grades[r._g] = (grades[r._g] || 0) + 1; });
  const sectors = Array.from(new Set(positions.map((h) => h.sector)));
  return {
    sub: isS
      ? 'Model (what the agent wants) vs Account (what the broker holds) · the gap is drift'
      : isA ? 'Account book — Alpaca ' + (c.env === 'live' ? 'live' : 'paper') + ' positions, costs from fills' : 'Model book — the agent’s simulated twin, as of ' + wdLabel(c.asof) + ' 17:05 ET',
    title: isS ? 'Model vs Account' : isA ? 'Account positions' : 'Model positions',
    tag: isS ? 'BOTH' : isA ? 'ACCOUNT' : 'MODEL',
    tagCls: isA ? 'acct' : '',
    count: rows.length === all.length ? all.length + ' positions' : rows.length + ' of ' + all.length + ' positions',
    frCls: isA ? (err ? 'red' : '') : c.data === 'stale' ? 'red' : '',
    frL: isA ? (err ? 'Broker unreachable · last ' + (c.facts.broker?.lastOk ?? '—') : 'Account · ' + (c.facts.accountAt ?? '—')) : modelFresh.l,
    errNote: isA && err && acct,
    errText: 'Broker unreachable — showing the last known account positions from ' + (c.facts.broker?.lastOk ?? '—') + ', valued at the last close.',
    noAcct: (isA || isS) && !acct,
    main: !isS && !(isA && !acct),
    side: isS && acct,
    cols: holdingsColumns(colsOn),
    rows,
    none: rows.length === 0 && all.length > 0,
    n: String(all.length),
    tMV: usd(mv),
    tW: f((mv / eq) * 100, 1) + '%',
    tU: susd(tu),
    tUCls: tn(tu),
    tR: '$0.00',
    tRCls: 'muted',
    cash: usd(isA ? c.accountCash ?? 0 : c.cash),
    eq: usd(eq),
    tC: wc == null ? '—' : String(wc),
    tBand: wc == null ? 'none' : band(wc),
    tGrades: Object.keys(grades).sort().map((k) => grades[k] + ' × ' + k).join(' · '),
    sectors,
  };
}

/* ───────── side-by-side ───────── */

export interface SideRow {
  s: string;
  mSh: string;
  aSh: string;
  dSh: string;
  dCls: string;
  mV: string;
  aV: string;
  dV: string;
  dVCls: string;
  mA: string;
  aA: string;
  slip: string;
  slipCls: string;
  ex: string;
}

export function selectSide(c: Ctx, positions: Position[]) {
  const mEq = c.equity;
  const aEq = acctEquity(positions, c);
  let driftV = 0;
  let nDiff = 0;
  const rows: SideRow[] = positions.map((h) => {
    const a = acctShares(h);
    const d = a - h.shares;
    const mV = h.shares * h.last;
    const aV = a * h.last;
    const slip = h.account?.slippageBps ?? 0;
    driftV += Math.abs(d) * h.last;
    if (d) nDiff += 1;
    const ex = d === 0
      ? 'Shares match · ' + (slip >= 0 ? '+' : '−') + f(slip, 1) + ' bps fill slippage on entry'
      : h.account?.drift?.row ?? 'Shares differ';
    return {
      s: h.symbol,
      mSh: String(h.shares), aSh: String(a),
      dSh: d === 0 ? '0' : (d > 0 ? '+' : '−') + Math.abs(d),
      dCls: d === 0 ? '' : Math.abs(d) > 2 || h.account?.drift?.short === 'reconciliation break' ? 'danger' : 'warn',
      mV: usd(mV), aV: usd(aV), dV: susd(aV - mV), dVCls: tn(aV - mV),
      mA: usd(h.avgCost), aA: usd(h.account?.avgCost ?? h.avgCost),
      slip: (slip > 0 ? '+' : slip < 0 ? '−' : '') + f(slip, 1) + ' bps',
      slipCls: Math.abs(slip) > 10 ? 'danger' : '',
      ex,
    };
  });
  const drift = (driftV / mEq) * 100;
  return {
    rows,
    drift: f(drift, 1) + '%',
    noteCls: drift > 1.5 ? 'warn' : 'info',
    note: 'Drift ' + f(drift, 1) + '% of equity vs the 1.5% band · ' + nDiff + (nDiff === 1 ? ' name differs' : ' names differ') + ' · tolerance ±2 shares or 5% per name; persistent drift is a P1',
    mEq: usd(mEq), aEq: usd(aEq), dEq: susd(aEq - mEq), dEqCls: tn(aEq - mEq),
    mCash: usd(c.cash), aCash: usd(c.accountCash ?? 0),
  };
}

/* ───────── drawer ───────── */

export interface DrawerOrder {
  side: string;
  sideCls: 'buy' | 'sell';
  q: string;
  when: string;
  px: string;
  lc: LcStep[];
  why: string;
}

export function selectDrawer(c: Ctx, h: Position, positions: Position[], intents: OrderIntent[], orders: HistOrder[], dBook: 'model' | 'account', lots?: HoldingDetailPayload['lots']) {
  const acct = c.env !== 'ghost';
  const isA = dBook === 'account' && acct;
  const sh = isA ? acctShares(h) : h.shares;
  const avg = isA && h.account ? h.account.avgCost : h.avgCost;
  const eq = isA ? acctEquity(positions, c) : c.equity;
  const val = sh * h.last;
  const u = (h.last - avg) * sh;
  const w = (val / eq) * 100;
  const cv = confOf(h, c);
  const sv = sharia(h, c);
  const ex = exitOf(h);
  const locked = c.controls.lockedSymbols.includes(h.symbol);
  const forced = c.controls.forcedExits.includes(h.symbol);
  const pend = pendingRows(intents, positions, c).filter((o) => o.symbol === h.symbol);
  const ords: DrawerOrder[] = pend
    .map((o) => ({ side: o.side, sideCls: (o.side === 'BUY' ? 'buy' : 'sell') as DrawerOrder['sideCls'], q: o.qtyLabel, when: 'next open · ' + o.state, px: 'ref ' + usd(o.refClose), lc: lcPending(o, c), why: o.reason }))
    .concat(orders.filter((o) => o.symbol === h.symbol).map((o) => ({
      side: o.side, sideCls: (o.side === 'BUY' ? 'buy' : 'sell') as DrawerOrder['sideCls'],
      q: (acct ? o.accountShares || o.shares : o.shares) + ' sh', when: 'filled ' + wdLabel(o.fillDate), px: '@ ' + usd(acct ? o.fillPrice : o.officialOpen), lc: lcHist(o, acct), why: o.reason,
    })));
  const aS = acctShares(h);
  const dS = aS - h.shares;
  const aAvg = h.account?.avgCost ?? h.avgCost;
  const mU = (h.last - h.avgCost) * h.shares;
  const aU = (h.last - aAvg) * aS;
  const bps = (aAvg / h.avgCost - 1) * 1e4;
  const drift = dS === 0
    ? 'Shares match. The ' + f(Math.abs(bps), 1) + ' bps difference in average cost is fill slippage at the open.'
    : h.account?.drift?.detail ?? 'The account holds ' + aS + ' of ' + h.shares + '.';
  const lotRows = (lots && lots.length ? lots : [{ opened: h.entryDate, shares: h.shares, cost: h.avgCost }]).map((l) => {
    const q = isA ? sh : l.shares;
    const cost = isA ? avg : l.cost;
    const lu = (h.last - cost) * q;
    return { d: wdLabel(l.opened), q: String(q), c: usd(cost), v: usd(q * h.last), u: susd(lu), cls: tn(lu) };
  });
  return {
    s: h.symbol, n: h.name, sec: h.sector, ind: h.industry,
    g: sv.g, gCls: sv.gCls, c: cv ? String(cv.tot) : '—', band: cv ? cv.band : 'none', bandL: cv ? cv.bandL : 'Pending', locked, forced,
    u: susd(u), uP: spct((h.last / avg - 1) * 100), uCls: tn(u), val: usd(val), w: f(w, 1) + '%',
    isA,
    sh: String(sh), avg: usd(avg), last: usd(h.last), day: h.dayPct == null ? '' : spct(h.dayPct, 2), dayCls: h.dayPct == null ? 'dim' : tn(h.dayPct),
    cap: f(18 - w, 1) + ' pp below the 18% cap',
    ed: wdLabel(h.entryDate) + ' ' + h.entryDate.slice(0, 4),
    why: h.entryReason,
    ts: h.heldSessions + ' of 35 sessions · ' + (35 - h.heldSessions) + ' left',
    exCls: ex.cls, ex: ex.full,
    lots: lotRows,
    ords,
    acctOk: acct, noAcct: !acct,
    cmp: [
      { k: 'Shares', m: String(h.shares), a: String(aS), d: dS === 0 ? '0' : (dS > 0 ? '+' : '−') + Math.abs(dS), cls: dS ? 'warn' : 'dim' },
      { k: 'Avg cost', m: usd(h.avgCost), a: usd(aAvg), d: (bps >= 0 ? '+' : '−') + f(Math.abs(bps), 1) + ' bps', cls: 'dim' },
      { k: 'Value', m: usd(h.shares * h.last), a: usd(aS * h.last), d: susd((aS - h.shares) * h.last), cls: tn((aS - h.shares) * h.last) },
      { k: 'Unrealized', m: susd(mU), a: susd(aU), d: susd(aU - mU), cls: tn(aU - mU) },
    ],
    driftCls: dS ? 'warn' : 'ok',
    drift,
  };
}

/* ───────── price pane ───────── */

export interface PriceView {
  dates: string[];
  labels: string[];
  wlabels: string[];
  close: number[];
  sma50: (number | null)[];
  sma200: (number | null)[];
  avg: number;
  initialStop: number | null;
  trailingStop: number | null;
  entryIndex: number;
  entryText: string;
  lo: number;
  hi: number;
}

export const PRICE_SESSIONS = 70;

export function sma(ser: number[], k: number): (number | null)[] {
  return ser.map((_, i) => {
    if (i < k - 1) return null;
    let s = 0;
    for (let j = i - k + 1; j <= i; j++) s += ser[j];
    return s / k;
  });
}

/** null when the ledger holds no daily prices for this name (see `pricesNote`). */
export function selectPrice(h: Position, d: HoldingDetailPayload): PriceView | null {
  if (!d.prices.length) return null;
  const ser = d.prices.map((p) => p.close);
  const show = Math.min(PRICE_SESSIONS, ser.length);
  const s50 = sma(ser, 50).slice(-show);
  const s200 = sma(ser, 200).slice(-show);
  const P = ser.slice(-show);
  const vals = [...P, ...(s50.filter((x) => x != null) as number[]), ...(s200.filter((x) => x != null) as number[]), h.avgCost, ...(exitOf(h).stopP != null ? [exitOf(h).stopP as number] : [])];
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08;
  lo -= pad;
  hi += pad;
  const dates = d.prices.slice(-show).map((p) => p.date);
  return {
    dates,
    labels: dates.map(dayLabel),
    wlabels: dates.map(wdLabel),
    close: P,
    sma50: s50,
    sma200: s200,
    avg: h.avgCost,
    initialStop: h.initialStop != null && h.initialStop >= lo && h.initialStop <= hi ? h.initialStop : null,
    trailingStop: h.trailingStop != null && h.trailingStop >= lo && h.trailingStop <= hi ? h.trailingStop : null,
    entryIndex: show - h.heldSessions,
    entryText: 'Buy ' + h.shares + ' @ ' + usd(h.avgCost) + ' · ' + wdLabel(h.entryDate),
    lo,
    hi,
  };
}

/* ───────── confidence breakdown ───────── */

const CONF_NAMES = ['Signal', 'Risk room', 'Regime', 'Data'];
const CONF_W = ['40%', '30%', '20%', '10%'];

/** null until the insights step (M3) ledgers confidence for this holding. */
export function selectConf(c: Ctx, h: Position, trips: RoundTrip[], history: number[]) {
  const cv = confOf(h, c);
  if (!cv || !h.confidence) return null;
  const ex = exitOf(h);
  const fa = c.facts;
  const why = [
    (h.rank != null ? 'Rank ' + h.rank + ' (exit above 30)' : 'Rank n/a') + (h.smaStack ? ' · ' + h.smaStack : '') + (h.offHighPct != null ? ' · ' + h.offHighPct + '% off the 52-week high' : ''),
    (h.rankExit ? 'Rank exit triggered' : ex.k + ' ' + ex.p + ', ' + ex.d) + ' · ' + (35 - h.heldSessions) + ' sessions left on the time stop',
    fa.regime ?? 'Market backdrop not available',
    c.data === 'stale' && fa.failing
      ? 'Data gate tripped since ' + wdLabel(fa.failing.from) + ' · last good data ' + wdLabel(fa.model.asof) + ' — inputs are stale'
      : h.crossSource === 'agree' ? 'Data gate passed · the second source agrees' : 'Data gate passed · second source unavailable for this name',
  ];
  const inBand = trips.filter((r) => r.confAtEntry != null && band(r.confAtEntry) === cv.band);
  const wins = inBand.filter((r) => r.pnl > 0).length;
  const name = { high: 'High', med: 'Medium', low: 'Low' }[cv.band];
  const live = inBand.length ? 'Live so far: ' + wins + ' of ' + inBand.length + '.' : 'Live: no round trips yet.';
  const hist = history.length ? history : [h.confidence.atEntry, cv.tot];
  return {
    tot: String(cv.tot), band: cv.band, bandL: cv.bandL, chip: cv.band === 'low' ? 'warn' : '',
    c0: String(h.confidence.atEntry),
    spark: path(hist, 0, 100, 100, 30),
    n: String(h.heldSessions),
    segs: cv.segs,
    subs: cv.c.map((v, i) => ({ n: CONF_NAMES[i], w: CONF_W[i], v: String(v), cls: v < 40 ? 'warn' : '', why: why[i] })),
    cal: name + ' band historically: NN% of round trips profitable (OOS 2023–26) — computed in M3. ' + live,
  };
}

export function selectShariaCard(c: Ctx, h: Position): ShariaCard {
  return sharia(h, c);
}
