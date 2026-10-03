// Performance (M2) and Agent (M3) selectors. Every number comes from the
// server (twin, account, OOS reference); missing values render "—" or
// "Pending", never an estimate.

import type { AgentPayload, MetricRow, PerformancePayload } from '@/api/types';
import { f, hbars, path, spct, susd, tn } from '@/lib/format';
import { dayLabel, wdLabel } from '@/lib/dates';

export type PerfTab = 'equity' | 'returns' | 'attribution' | 'execution';
export const PERF_TABS: { k: PerfTab; l: string }[] = [
  { k: 'equity', l: 'Equity' }, { k: 'returns', l: 'Returns' }, { k: 'attribution', l: 'Attribution' }, { k: 'execution', l: 'Execution quality' },
];

/** Signed number: "−4.09", "0.36" (f() alone drops the sign). */
export const sn = (v: number, d = 2) => (v < 0 && Number(f(v, d)) !== 0 ? '−' : '') + f(v, d);

/** Metric value in its unit; null → "—". Percent metrics are fractions. */
export function metricText(v: number | null, unit: MetricRow['unit']): string {
  if (v == null || !Number.isFinite(v)) return '—';
  if (unit === 'pct') return spct(v * 100, 1);
  if (unit === 'count') return String(Math.round(v));
  return sn(v, 2);
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Heat-map cell: tint scales with |return| up to ±10% a month. */
export function heatCell(v: number | null): { v: string; cls: string; bg: string } {
  if (v == null) return { v: '', cls: 'na', bg: 'transparent' };
  const k = Math.min(1, Math.abs(v) / 0.1);
  const tone = v >= 0 ? 'var(--pos)' : 'var(--neg)';
  return { v: spct(v * 100, 1), cls: '', bg: `color-mix(in srgb, ${tone} ${Math.round(12 + k * 48)}%, transparent)` };
}

/** Waterfall bars from $0 to the total, then a total bar. Heights in % of the plot. */
export function waterfall(items: { label: string; value: number }[]) {
  let run = 0;
  const steps = items.map((i) => { const a = run; run += i.value; return { l: i.label, a, b: run, v: i.value }; });
  const all = [0, ...steps.flatMap((s) => [s.a, s.b])];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const y = (v: number) => ((hi - v) / span) * 100;
  const bars = steps.map((s) => {
    const top = y(Math.max(s.a, s.b));
    const h = Math.max(0.6, (Math.abs(s.b - s.a) / span) * 100);
    return { l: s.l, cls: s.v >= 0 ? 'pos' : 'neg', top, h, v: susd(s.v, 0), lCls: tn(s.v), lt: Math.max(0, top - 9), t: s.l + ': ' + susd(s.v) };
  });
  const total = { l: 'Total', cls: 'tot', top: y(Math.max(0, run)), h: Math.max(0.6, (Math.abs(run) / span) * 100), v: susd(run, 0), lCls: tn(run), lt: Math.max(0, y(Math.max(0, run)) - 9), t: 'Since start: ' + susd(run) };
  return { bars: steps.length ? [...bars, total] : [], zero: y(0), total: run };
}

export function selectPerformance(p: PerformancePayload) {
  const metrics = p.metrics.map((m) => ({
    k: m.label, key: m.key, n: m.note,
    m: metricText(m.model, m.unit), a: metricText(m.account, m.unit), b: metricText(m.bench, m.unit), r: metricText(m.ref, m.unit),
    mc: m.unit === 'pct' && m.model != null ? tn(m.model) : '', ac: m.unit === 'pct' && m.account != null ? tn(m.account) : '', bc: m.unit === 'pct' && m.bench != null ? tn(m.bench) : '',
  }));
  const hm = p.monthly.map((r) => ({
    l: r.label, live: r.live,
    c: r.months.map((v, i) => ({ ...heatCell(v), t: r.label + ' ' + MONTHS[i] + (v == null ? ': no data' : ': ' + spct(v * 100, 2)) })),
    t: spct(r.year * 100, 1), tCls: tn(r.year),
  }));
  const per = (k: keyof PerformancePayload['periods']) => ({ d: susd(p.periods[k].pnl), p: spct(p.periods[k].pct * 100, 2), cls: tn(p.periods[k].pnl) });
  const ref = p.reference;
  return {
    sub: 'Model (twin) vs account vs NASDAQ Composite · since ' + wdLabel(p.since) + ' · ' + p.sessions + ' sessions',
    short: p.sessions < 63,
    metrics,
    months: MONTHS,
    hm,
    periods: { today: per('today'), wtd: per('wtd'), mtd: per('mtd'), all: per('all') },
    wf: waterfall(p.byHolding),
    bySec: hbars(p.bySector.map((x) => ({ l: x.label, v: x.value }))),
    gap: p.gap ? hbars(p.gap.map((x) => ({ l: x.label, v: x.value }))) : null,
    gapTotal: p.gap ? p.gap[p.gap.length - 1]?.value ?? 0 : null,
    dividends: { gross: susd(p.dividends.gross), wh: susd(p.dividends.withholding), net: susd(p.dividends.gross + p.dividends.withholding) },
    refNote: ref.sharpe == null ? 'OOS reference not found (out/oos_metrics.json).' :
      'OOS reference' + (ref.window ? ' (' + ref.window.join(' → ') + ')' : '') + ': Sharpe ' + f(ref.sharpe, 2) + (ref.mdd != null ? ', max drawdown ' + spct(ref.mdd * 100, 1) : '') + (ref.cagr != null ? ', CAGR ' + spct(ref.cagr * 100, 1) : '') + '.',
  };
}

export function selectExecution(p: PerformancePayload) {
  const x = p.execution;
  if (!x) return null;
  const vs = x.fills.map((q) => q.bps);
  const lim = Math.max(20, ...vs.map((v) => Math.abs(v))) * 1.1;
  const days = [...new Set(x.fills.map((q) => q.date))].sort();
  const xi = (d: string) => (days.length < 2 ? 50 : (days.indexOf(d) / (days.length - 1)) * 100);
  const yp = (v: number) => ((v + lim) / (2 * lim)) * 100;
  const teMax = Math.max(0.01, ...x.trackingError.map((t) => t.value));
  return {
    has: x.fills.length > 0,
    avg: x.avgBps == null ? '—' : sn(x.avgBps, 1) + ' bps',
    out: String(x.outliers),
    missed: String(x.missed),
    te: x.trackingError.length ? f(x.trackingError[x.trackingError.length - 1].value * 100, 2) + '%' : '—',
    pts: x.fills.map((q) => ({ x: xi(q.date), y: yp(q.bps), cls: Math.abs(q.bps) > 10 ? 'out' : q.side === 'sell' ? 'sell' : '', t: q.symbol + ' ' + q.side + ' ' + wdLabel(q.date) + ': ' + sn(q.bps, 1) + ' bps' })),
    bandTop: 100 - yp(10), bandH: yp(10) - yp(-10),
    yt: [-lim, -lim / 2, 0, lim / 2, lim].map((v) => ({ p: 100 - yp(v), l: (v > 0 ? '+' : v < 0 ? '−' : '') + f(Math.abs(v), 0) })),
    xt: days.length ? [days[0], days[days.length - 1]].map((d) => ({ p: xi(d), l: dayLabel(d) })) : [],
    teBars: x.trackingError.map((t) => ({ l: MONTHS[Number(t.month.slice(5, 7)) - 1], v: f(t.value * 100, 2) + '%', h: (t.value / Math.max(teMax, 0.005)) * 90, over: t.value > 0.005 })),
    teBand: 100 - (0.005 / Math.max(teMax, 0.005)) * 90,
  };
}

/* ───────── Agent ───────── */

const PARAM_NOTES: Record<string, string> = {
  EXP_MAX: 'Most of the portfolio the agent may invest (the rest stays cash)',
  RISK_PER_TRADE: 'How much of the portfolio one position may lose before its stop',
  STOP_ATR: 'Initial stop distance, in ATRs below the entry price',
  TRAIL_ATR: 'Trailing stop distance, in ATRs below the highest price',
  TIME_STOP: 'Sessions before a position that is not working is sold',
  RANK_BUFFER: 'How far a holding may slip in the momentum ranking before it is sold',
  TARGET_VOL: 'The yearly bumpiness the portfolio aims for; higher = more invested',
  W3: 'Weight of 3-month momentum in the ranking',
  W6: 'Weight of 6-month momentum in the ranking',
  W12: 'Weight of 12-month momentum in the ranking',
};

export function paramNote(k: string): string {
  return PARAM_NOTES[k] ?? '';
}

export function selectAgent(a: AgentPayload) {
  const pos = (v: number | null, lo: number, hi: number) => (v == null ? null : Math.max(0, Math.min(100, ((v - lo) / (hi - lo || 1)) * 100)));
  const num = (v: number | null) => (v == null ? '—' : v % 1 === 0 ? f(v, 0) : Math.abs(v) < 0.1 ? f(v, 3) : Math.abs(v) < 10 ? f(v, 2) : f(v, 1));
  const params = a.params.map((p) => ({ k: p.k, v: num(p.v), lo: num(p.lo), hi: num(p.hi), fzv: num(p.frozen), pos: pos(p.v, p.lo, p.hi), fz: pos(p.frozen, p.lo, p.hi), d: paramNote(p.k), moved: p.v != null && p.frozen != null && Math.abs(p.v - p.frozen) > 1e-9 }));
  const sent = a.sentiment.filter((s) => s.s != null);
  const pSent = sent.length > 1 ? path(sent.map((s) => s.s), -1, 1, 1000, 200) : '';
  const xt = sent.length > 1 ? [0, Math.floor((sent.length - 1) / 2), sent.length - 1].map((i) => ({ p: (i / (sent.length - 1)) * 100, l: dayLabel(sent[i].date) })) : [];
  const r = a.regime;
  const regime = [
    r.score != null && { l: 'Regime dial', v: sn(r.score, 2), x: 0, w: clamp(r.score * 100), ref: 50, lo: '0', hi: '1', note: 'defensive ↔ trending' },
    r.ixic_vs_sma200 != null && { l: 'NASDAQ vs its 200-day average', v: spct(r.ixic_vs_sma200 * 100, 1), x: 0, w: clamp(50 + r.ixic_vs_sma200 * 250), ref: 50, lo: '−20%', hi: '+20%', note: 'above = up-trend' },
    r.ixic_vs_sma50 != null && { l: 'NASDAQ vs its 50-day average', v: spct(r.ixic_vs_sma50 * 100, 1), x: 0, w: clamp(50 + r.ixic_vs_sma50 * 500), ref: 50, lo: '−10%', hi: '+10%', note: 'short-term trend' },
    r.breadth != null && { l: 'Breadth (names above their 50-day)', v: f(r.breadth * 100, 0) + '%', x: 0, w: clamp(r.breadth * 100), ref: 50, lo: '0%', hi: '100%', note: 'how many stocks join in' },
  ].filter(Boolean) as { l: string; v: string; x: number; w: number; ref: number; lo: string; hi: string; note: string }[];
  const diff = (c: Record<string, number> | null | undefined) => Object.entries(c ?? {}).map(([k, v]) => k + ' → ' + num(v)).join(' · ');
  const trail = [
    ...(a.adaptPaused ? [{ g: '❚❚', cls: 'ovr', d: 'Paused' + (a.adaptPausedSince ? ' since ' + wdLabel(a.adaptPausedSince) : ''), t: 'adapt() is paused by the owner — parameters stay frozen.', diff: '' }] : []),
    ...(a.nextAdapt ? [{ g: '◇', cls: 'adp', d: 'Next adapt() ' + wdLabel(a.nextAdapt), t: 'Every ' + a.adaptEvery + ' sessions · ' + (a.sessions % a.adaptEvery) + ' of ' + a.adaptEvery + ' done', diff: '' }] : []),
    ...a.adaptations.map((x) => ({ g: '◆', cls: 'adp', d: wdLabel(x.date) + ' · live', t: x.note || 'Parameters re-tuned', diff: diff(x.changes) })),
    ...a.oosAdaptations.map((x) => ({ g: '◆', cls: 'muted', d: x.date + ' · OOS', t: x.note || 'Backtest adaptation', diff: diff(x.changes) })),
  ];
  const BL = { high: 'High ≥ 70', med: 'Medium 40–69', low: 'Low < 40' } as const;
  const cal = (['high', 'med', 'low'] as const).map((b) => {
    const o = a.calibration?.bands.find((x) => x.band === b);
    const l = a.liveBands.find((x) => x.band === b);
    return {
      band: b, l: BL[b],
      oosN: o ? o.n.toLocaleString('en-US') : '—',
      oosHit: o?.trade_won_rate != null ? f(o.trade_won_rate * 100, 0) + '%' : o?.hit_rate != null ? f(o.hit_rate * 100, 0) + '%' : '—',
      oosRet: o?.avg_return != null ? spct(o.avg_return * 100, 1) : '—', oosRetCls: o?.avg_return != null ? tn(o.avg_return) : '',
      n: l ? String(l.n) : '0',
      hit: l?.hit != null ? f(l.hit * 100, 0) + '%' : '—',
      ret: l?.ret != null ? spct(l.ret * 100, 1) : '—', retCls: l?.ret != null ? tn(l.ret) : '',
    };
  });
  const liveN = a.liveBands.reduce((s, b) => s + b.n, 0);
  return {
    params, pSent, xt, regime, trail, cal, liveN,
    mood: a.mood ?? '—',
    sent: sent.length ? sn(sent[sent.length - 1].s, 2) : '—',
    journal: a.journal.map((j) => ({ d: wdLabel(j.date), m: j.mood ?? '—', s: j.sentiment == null ? '—' : sn(j.sentiment, 2), t: j.note })),
    adaptL: a.adaptPaused ? 'adapt() paused' : a.nextAdapt ? 'Next adapt() ' + wdLabel(a.nextAdapt) : 'adapt() on',
    adaptCls: a.adaptPaused ? 'warn' : 'info',
    calNote: a.calibration
      ? 'OOS calibration over ' + a.calibration.position_days.toLocaleString('en-US') + ' position-days (' + a.calibration.window.join(' → ') + '): share of holdings whose trade ended in a profit, by confidence band. ' + (liveN < 30 ? 'The live sample (' + liveN + ' round trips) is too small to judge.' : '')
      : 'OOS calibration not computed yet (python -m live.calibration writes out/confidence_calibration.json).',
  };
}

const clamp = (v: number) => Math.max(0, Math.min(100, v));
