// Mock API: builds every v1 payload from the prototype fixtures for one
// scenario (environment × data health × trading state × role). Used by MSW in
// `npm run dev:mock`, by Storybook (one scenario per state-catalogue frame)
// and by the selector tests.
//
// Fixture values are the prototype's: positions, prices and some round trips
// are real (Fri 25 Sep 2026); everything else is illustrative. Never seed
// production with this file.

import sample from './sample-data.json';
import { rng, seed } from '@/lib/format';
import { sessionsEndingAt } from '@/lib/dates';
import type { HoldingDetailPayload } from '@/api/types';
import type {
  Alert,
  AlertsPayload,
  CellStatus,
  CompliancePayload,
  ControlsState,
  DataHealth,
  Env,
  HealthPayload,
  HistoryPayload,
  HoldingsPayload,
  Intent,
  OverviewPayload,
  PendingPayload,
  Position,
  Rescreen,
  Role,
  RoadmapPayload,
  RoundTripsPayload,
  SystemStatus,
  TradingState,
} from '@/api/types';

export interface Scenario {
  env: Env;
  health: DataHealth;
  trading: TradingState;
  role: Role;
  released: boolean;
  haltCleared: boolean;
  controls: ControlsState;
}

export const defaultControls = (): ControlsState => ({
  lockedSymbols: [],
  forcedExits: [],
  manualOrders: [],
  excludedSymbols: ['PEP', 'BKR'],
  excludedMore: 23,
  grossCap: null,
  pauseAdapt: false,
});

export const defaultScenario = (): Scenario => ({
  env: 'paper',
  health: 'loaded',
  trading: 'running',
  role: 'owner',
  released: false,
  haltCleared: false,
  controls: defaultControls(),
});

/* ───────── fixture helpers ───────── */

const MON: Record<string, string> = { Aug: '08', Sep: '09', Oct: '10' };

/** "Tue 22 Sep" or "22 Sep" → "2026-09-22" (fixture dates are Aug–Oct 2026). */
export function labelIso(label: string): string {
  const p = label.trim().split(' ');
  const [d, m] = p.length === 3 ? [p[1], p[2]] : [p[0], p[1]];
  return '2026-' + MON[m] + '-' + d.padStart(2, '0');
}

const REVIEW: Record<string, { keyword: string; category: string }> = {
  ROKU: { keyword: 'streaming entertainment platform', category: 'media & entertainment' },
};

type RawHolding = (typeof sample.holdings)[number] & { review?: boolean; div?: boolean; rankExit?: boolean };

function driftNote(sym: string, aSh: number, sh: number): NonNullable<Position['account']>['drift'] {
  if (aSh === sh) return null;
  if (sym === 'AMD') return { row: 'Buy trimmed to available cash at submit (F6): account bought 4 of 7', short: 'buy trimmed to cash', detail: 'The account holds 4 of 7: the buy was trimmed to available cash at submit (F6). Drift 2.1% of equity — explained, alert A-38.' };
  return { row: 'Reconciliation break — 1 share missing after the open (halt)', short: 'reconciliation break', detail: 'The account holds ' + aSh + ' of ' + sh + ' — a reconciliation break; the submit is halted until a cause is recorded.' };
}

function position(h: RawHolding, sc: Scenario): Position {
  const aSh = h.s === 'ROKU' && sc.trading === 'halted' && !sc.haltCleared ? 74 : h.aSh;
  return {
    symbol: h.s,
    name: h.n,
    sector: h.sec,
    industry: h.ind,
    shares: h.sh,
    avgCost: h.avg,
    last: h.last,
    dayPct: h.day,
    entryDate: labelIso(h.ed),
    heldSessions: h.held,
    atr: h.atr,
    high: h.hi,
    rank: h.rank,
    offHighPct: h.off,
    smaStack: h.stack,
    initialStop: h.init,
    trailingStop: h.trailP,
    confidence: { signal: h.conf[0], riskRoom: h.conf[1], regime: h.conf[2], data: h.conf[3], atEntry: h.c0 },
    crossSource: h.cs as Position['crossSource'],
    debtPct: h.debt,
    cashPct: h.cash,
    review: h.review ? REVIEW[h.s] ?? { keyword: 'review', category: 'business screen' } : null,
    entryReason: h.why,
    rankExit: !!h.rankExit,
    nextDividend: h.div ? { perShare: 0.115, shares: h.sh, payDate: '2026-10-20' } : null,
    account: sc.env === 'ghost' ? null : { shares: aSh, avgCost: h.aAvg, slippageBps: h.slip, drift: driftNote(h.s, aSh, h.sh) },
  };
}

function clock(sc: Scenario): SystemStatus['clock'] {
  if (sc.health === 'stale') return { d: 'Thu 1 Oct', t: '18:03 ET' };
  if (sc.trading === 'halted') return { d: 'Mon 28 Sep', t: '10:04 ET' };
  if (sc.trading === 'held') return { d: 'Fri 25 Sep', t: '19:22 ET' };
  return { d: 'Fri 25 Sep', t: '18:03 ET' };
}

export function system(sc: Scenario): SystemStatus {
  return {
    env: sc.env,
    health: sc.health,
    trading: sc.trading,
    released: sc.released,
    haltCleared: sc.haltCleared,
    stopAt: sc.trading === 'stopped' ? '18:04 ET' : null,
    flatten: false,
    clock: clock(sc),
  };
}

const PHASES: Record<Env, OverviewPayload['phase']> = {
  ghost: { n: 1, of: 10, title: 'Phase 1 · Ghost', gate: 'Gate streak 1 / 10 deterministic sessions', dates: 'earliest pass Fri 9 Oct · phase ends Fri 30 Oct', decision: 'Next decision: D1 Sharia rulings — 35 days' },
  paper: { n: 3, of: 10, title: 'Phase 2 · Paper (preview)', gate: 'Clean paper sessions 3 / 10 — no P1, no break, slippage ≤ 10 bps', dates: 'from Mon 2 Nov · earliest pass Fri 13 Nov', decision: 'Next decision: D1 Sharia rulings — 35 days' },
  live: { n: 4, of: 10, title: 'Phase 5 · Real money (preview)', gate: 'First 10 pilot sessions in approval mode · 4 / 10', dates: 'pilot from Mon 10 May 2027 at the earliest', decision: 'Review at −15% from the pilot high (D4)' },
};

/* ───────── payloads ───────── */

export function overview(sc: Scenario): OverviewPayload {
  const acct = sc.env !== 'ghost';
  return {
    system: system(sc),
    controls: sc.controls,
    me: { user: sc.role === 'owner' ? 'owner@console' : 'reviewer@console', role: sc.role },
    asof: sample.asof,
    twinStart: sample.twinStart,
    startCapital: sample.startCapital,
    equity: sample.equity,
    cash: sample.cash,
    accountCash: acct ? sample.accountCash : null,
    equityCurve: sample.equityCurve.map((p) => ({ date: p.date, model: p.model, account: acct ? p.account : null, benchmark: p.benchmark })),
    markers: [
      { date: '2026-09-10', kind: 'override', text: 'Override — pause entries (owner): data check after a vendor outage' },
      { date: '2026-09-11', kind: 'override', text: 'Override — entries resumed; held night released' },
      { date: '2026-09-16', kind: 'halt', text: 'Halt — reconciliation drill, cleared 10:22 ET' },
    ],
    phase: PHASES[sc.env],
  };
}

export function holdings(sc: Scenario): HoldingsPayload {
  const rows = sc.health === 'empty' ? [] : (sample.holdings as RawHolding[]).map((h) => position(h, sc));
  return { asof: sample.asof, positions: rows };
}

export function pending(sc: Scenario): PendingPayload {
  const off = sc.health === 'stale' || sc.health === 'empty';
  const intents: Intent[] = off
    ? []
    : sample.pendingOrders.map((o) => {
        const raw = o as typeof o & { grNote?: string };
        return {
          id: o.id,
          symbol: o.s,
          name: o.n,
          side: o.side as Intent['side'],
          shares: Number(o.qtyS),
          qtyLabel: o.qty,
          amountLabel: o.amt,
          refClose: o.ref,
          estValue: o.est,
          reason: o.why,
          source: o.src as Intent['source'],
          guardrail: o.gr,
          guardrailNote: raw.grNote ?? '',
          clientOrderId: o.cid,
        };
      });
  return { asof: sample.asof, nextOpen: sc.health === 'stale' ? '2026-10-02' : '2026-09-28', intents };
}

export function history(sc: Scenario): HistoryPayload {
  const orders = sc.health === 'empty' ? [] : sample.orderHistory.map((o) => {
    const raw = o as typeof o & { qa?: number };
    return {
      id: o.id,
      decisionDate: labelIso(o.dd),
      fillDate: labelIso(o.fd),
      symbol: o.s,
      side: o.side as 'BUY' | 'SELL',
      shares: o.q,
      accountShares: raw.qa ?? null,
      decisionClose: o.dc,
      officialOpen: o.op,
      fillPrice: o.fp,
      fees: o.fee,
      realized: o.rp,
      heldDays: o.days,
      reason: o.why,
    };
  });
  return { since: sample.twinStart, total: sc.health === 'empty' ? 0 : 44, feesSinceStart: 28.56, orders };
}

export function roundTrips(sc: Scenario): RoundTripsPayload {
  return {
    fees: 28.56,
    trips: sc.health === 'empty' ? [] : sample.roundTrips.map((r) => ({
      symbol: r.s,
      sector: r.sec,
      entryDate: labelIso(r.e),
      exitDate: labelIso(r.x),
      days: r.d,
      entryPrice: r.ep,
      exitPrice: r.xp,
      pnl: r.pnl,
      exitReason: r.r as RoundTripsPayload['trips'][number]['exitReason'],
      confAtEntry: r.c,
    })),
  };
}

type RawAlert = (typeof sample.alerts)[number] & { only?: string; ack?: boolean; res?: boolean; acct?: boolean; note?: string };

export function alerts(sc: Scenario, acked: Record<string, true> = {}): AlertsPayload {
  const out: Alert[] = [];
  for (const a of sample.alerts as RawAlert[]) {
    if (a.only === 'stale' && sc.health !== 'stale') continue;
    if (a.only === 'error' && (sc.health !== 'error' || sc.env === 'ghost')) continue;
    if (a.only === 'halted' && (sc.trading !== 'halted' || sc.haltCleared)) continue;
    if (a.only === 'held' && sc.trading !== 'held') continue;
    if (a.acct && sc.env === 'ghost') continue;
    if (a.id === 'A-40' && sc.controls.forcedExits.includes('ROKU')) continue;
    let status: Alert['status'] = a.res ? 'resolved' : a.ack ? 'acknowledged' : 'open';
    if (acked[a.id]) status = 'acknowledged';
    out.push({ id: a.id, priority: a.p as Alert['priority'], title: a.t, detail: a.d, source: a.src, githubIssue: a.gh, raisedAt: a.when, status, note: a.note ?? '' });
  }
  if (sc.trading === 'stopped') {
    out.unshift({ id: 'A-47', priority: 'P2', title: 'Kill switch active — trading stopped', detail: 'No orders are ledgered or sent until you resume through the preflight checklist', source: 'controls.json', githubIssue: null, raisedAt: 'Fri 25 Sep 18:04 ET', status: acked['A-47'] ? 'acknowledged' : 'open', note: '' });
  }
  return { alerts: out };
}

const RESCREENS: Rescreen[] = [
  {
    id: 'q4', date: 'Thu 1 Oct 2026', kind: 'Quarterly re-screen · Q4', file: '2026-10-01', dot: 'warn', summary: '25 newly non-compliant · 13 newly eligible · 0 held affected',
    stats: [{ l: 'Newly non-compliant', v: '25', cls: 'danger' }, { l: 'Newly eligible', v: '13', cls: '' }, { l: 'Held names affected', v: '0', cls: 'pos' }, { l: 'Forced exits caused', v: '0', cls: '' }],
    outTitle: 'Newly non-compliant → exclusions added to controls (block buys)', outTag: 'excluded',
    out: [['PEP', 'debt/mcap 31% ≥ 30%'], ['BKR', 'cash/mcap 31% ≥ 30%'], ['KHC', 'debt/mcap 30.6% ≥ 30%'], ['KDP', 'debt/mcap 30.8% ≥ 30%'], ['MDLZ', 'debt/mcap 30.4% ≥ 30%'], ['CSX', 'debt/mcap 30.2% ≥ 30%'], ['+19', 'more names, same rule']].map(([symbol, reason]) => ({ symbol, reason })),
    inTitle: 'Newly eligible · 13', in: ['RKLB', 'NBIS', 'IREN', 'OKTA', 'DOCU', 'ZM', 'TEAM', 'WDAY', 'CHKP', 'AKAM', 'FFIV', 'GEN', 'VRSN'],
    inNote: 'The universe is frozen for the evaluation: newly eligible names wait for the next declared redeploy.',
    note: 'No held name is affected. Exclusions act through controls.json; the twin’s universe stays frozen.', noteCls: 'ok',
  },
  {
    id: 'fix', date: 'Fri 25 Sep 2026', kind: 'Universe correction · 327 → 319', file: 'regression_2026-09-25_universe', dot: 'info', summary: '8 removed: 7 preferred lines and 1 keyword miss · 0 held affected',
    stats: [{ l: 'Removed', v: '8', cls: 'danger' }, { l: 'Universe now', v: '319', cls: '' }, { l: 'Held names affected', v: '0', cls: 'pos' }, { l: 'Sharpe (regression)', v: '1.22 → 1.26', cls: '' }],
    outTitle: 'Removed by the instrument screen and curated overrides (F4)', outTag: 'removed',
    out: [['BRKRP', 'preferred line — common shares only'], ['SMCIP', 'preferred line'], ['MCHPP', 'preferred line'], ['STRF', 'perpetual preferred'], ['STRC', 'perpetual preferred'], ['STRK', 'perpetual preferred'], ['SATA', 'perpetual preferred'], ['SFD', 'pork producer — keyword screen miss']].map(([symbol, reason]) => ({ symbol, reason })),
    inTitle: 'Regression · same frozen agent, OOS 2023-01-03 → 2026-08-04', in: [],
    inNote: 'Total return +207.6% → +216.8% · CAGR 36.8% → 38.0% · max drawdown −16.2% → −16.3% · trades 806 → 808. Path noise from a changed input, not an improvement.',
    note: 'The election figures remain the official OOS record; the corrected run is the reference for the deployed configuration.', noteCls: 'info',
  },
  {
    id: 'q3', date: 'Wed 1 Jul 2026', kind: 'Baseline screen · Q3', file: '2026-07-01', dot: 'ok', summary: '327 names pass · the election universe',
    stats: [{ l: 'Universe', v: '327', cls: '' }, { l: 'Review-flagged', v: '22', cls: 'warn' }, { l: 'Held', v: '—', cls: '' }, { l: 'Forced exits', v: '0', cls: '' }],
    outTitle: 'Changes', outTag: 'excluded', out: [], inTitle: '', in: [], inNote: '', note: 'Baseline for the OOS election record.', noteCls: 'info',
  },
];

export function compliance(): CompliancePayload {
  return {
    screenedOn: '2026-10-01',
    nextScreen: '2027-01-01',
    universeSize: 319,
    reviewFlagged: 22,
    excludedAfterRescreen: 25,
    universe: sample.universeSample.map((u) => ({ symbol: u.s, name: u.n, grade: u.g as 'A' | 'B' | 'C' | 'F', status: u.st as 'Compliant' | 'Under review' | 'Excluded', debtPct: u.debt, cashPct: u.cash, flag: u.flag })),
    rescreens: RESCREENS,
  };
}

/* ───────── health ───────── */

const DAYS_OK = [['Tue', '8 Sep'], ['Wed', '9 Sep'], ['Thu', '10 Sep'], ['Fri', '11 Sep'], ['Mon', '14 Sep'], ['Tue', '15 Sep'], ['Wed', '16 Sep'], ['Thu', '17 Sep'], ['Fri', '18 Sep'], ['Mon', '21 Sep'], ['Tue', '22 Sep'], ['Wed', '23 Sep'], ['Thu', '24 Sep'], ['Fri', '25 Sep']];
const DAYS_STALE = [['Mon', '14 Sep'], ['Tue', '15 Sep'], ['Wed', '16 Sep'], ['Thu', '17 Sep'], ['Fri', '18 Sep'], ['Mon', '21 Sep'], ['Tue', '22 Sep'], ['Wed', '23 Sep'], ['Thu', '24 Sep'], ['Fri', '25 Sep'], ['Mon', '28 Sep'], ['Tue', '29 Sep'], ['Wed', '30 Sep'], ['Thu', '1 Oct']];

export function health(sc: Scenario): HealthPayload {
  const stale = sc.health === 'stale';
  const g = sc.env === 'ghost';
  const err = sc.health === 'error';
  const days = stale ? DAYS_STALE : DAYS_OK;
  const stat = (k: 'A' | 'S' | 'B', i: number): CellStatus => {
    const day = days[i][0] + ' ' + days[i][1];
    if (stale && i >= 10) return k === 'A' ? 'fail' : k === 'S' ? 'skip' : 'ok';
    if (day === 'Wed 16 Sep' && k === 'B') return 'fail';
    if (day === 'Fri 11 Sep' && k === 'S') return 'held';
    if (!stale && i === 13 && k === 'S') return sc.trading === 'held' ? 'held' : sc.released ? 'ok' : 'skip';
    return 'ok';
  };
  const rec = (k: 'A' | 'S' | 'B', s: CellStatus, day: string): unknown => {
    if (k === 'A' && s === 'fail') return { step: 'cycle_a', session: day, asof: '2026-09-25', status: 'failed', reason: 'data gate tripped', checks: { ixic_at_asof: true, fetch_ok: 0.969, coverage_at_asof: 0.006, min_coverage: 0.95, cross_source: { compared: 1, unavailable: 39 } }, duration_s: 38, commit: '4e1a7c2' };
    if (k === 'A') return { step: 'cycle_a', session: day, status: 'ok', intents: 4, blocked: 1, twin_equity: 90407.14, sha256: '9c1e7a0d…a2b4b07', duration_s: 41, commit: '9f20b1d' };
    if (k === 'S' && s === 'held') return { step: 'cycle_submit', session: day, status: 'held', reason: 'approval_mode', released_at: day === 'Fri 11 Sep' ? '22:03 ET' : null };
    if (k === 'S' && s === 'skip') return { step: 'cycle_submit', session: day, status: stale ? 'skipped' : 'scheduled', reason: stale ? 'no plan for this session' : 'runs at 19:15 ET' };
    if (k === 'S') return { step: 'cycle_submit', session: day, status: 'ok', sent: 3, accepted: 3, mode: g ? 'rehearsal' : 'paper' };
    if (k === 'B' && s === 'fail') return { step: 'cycle_b', session: day, status: 'break', diffs: [{ symbol: 'PLTR', expected: 60, actual: 59 }], halt: true, note: 'drill — cleared 10:22 ET' };
    return { step: 'cycle_b', session: day, status: 'ok', reconciled: 10, breaks: 0, avg_slippage_bps: 3.8 };
  };
  const cycles = { A: [] as CellStatus[], S: [] as CellStatus[], B: [] as CellStatus[] };
  const records: Record<string, unknown> = {};
  (['A', 'S', 'B'] as const).forEach((k) => days.forEach((d, i) => {
    const s = stat(k, i);
    cycles[k].push(s);
    records[k + i] = rec(k, s, d[0] + ' ' + d[1]);
  }));
  const okChecks = [{ ok: true, label: 'NASDAQ Composite bar at asof', value: 'present', min: '' }, { ok: true, label: 'Fetch ok', value: '99.4%', min: 'min 95%' }, { ok: true, label: 'Coverage at asof', value: '100% · 319 / 319', min: 'min 95%' }, { ok: true, label: 'Cross-source check', value: '38 agree · 2 unavailable', min: '0 disagree' }];
  const badChecks = [{ ok: true, label: 'NASDAQ Composite bar at asof', value: 'present', min: '' }, { ok: true, label: 'Fetch ok', value: '96.9%', min: 'min 95%' }, { ok: false, label: 'Coverage at asof', value: '0.6%', min: 'min 95%' }, { ok: null, label: 'Cross-source check', value: '1 compared · 39 unavailable', min: 'up to 40' }];
  const broker = g
    ? [{ k: 'Mode', v: 'Ghost — no broker; rehearsal against the twin’s book', cls: '' }, { k: 'Paper account', v: 'opens by Fri 23 Oct (task P1)', cls: 'dim' }, { k: 'Keys on GitHub', v: 'none yet (paper keys only, ever)', cls: 'dim' }, { k: 'Live keys', v: 'never on GitHub — Unraid box only', cls: 'dim' }]
    : [{ k: 'Endpoint', v: sc.env === 'live' ? 'Alpaca live · cash account' : 'Alpaca paper · paper-api', cls: '' }, { k: 'Reachable', v: err ? '✕ timeout after 10 s' : '✓ 142 ms', cls: err ? 'danger' : 'pos' }, { k: 'Account status', v: 'ACTIVE · cash only (margin off)', cls: '' }, { k: 'Buying power', v: '$6,544.20', cls: '' }, { k: 'Open orders', v: err ? 'unknown' : '0 · tonight’s submit at 19:15', cls: err ? 'warn' : '' }, { k: 'Last API call', v: err ? '17:41:08 ET' : '18:01:52 ET', cls: '' }, { k: 'Key permissions', v: 'trading only · no transfers · rotate quarterly', cls: 'dim' }];
  const sch = (step: string, expected: string) => ({ step, expected, last: '—', duration: '—', status: 'Scheduled', dot: 'off', cls: 'muted' });
  const ixDown = err && g;
  return {
    summary: stale ? 'Cycle A failing since Mon 28 Sep · data gate · model book stuck at Fri 25 Sep' : err ? (g ? 'Indexer unreachable — read model 14 min behind' : 'Broker gateway unreachable since 17:41 ET') : 'All scheduled steps healthy · last Cycle A Fri 25 Sep 17:05 ET',
    degraded: stale || err,
    sessions: days.map((d) => ({ dow: d[0], label: d[1] })),
    cycles,
    records,
    defaultCell: 'A13',
    gate: {
      streak: 1,
      target: 10,
      stalled: stale ? 'Stalled — 4 failed sessions' : null,
      earliestPass: 'Fri 9 Oct',
      hashes: stale
        ? [...['Thu 1 Oct', 'Wed 30 Sep', 'Tue 29 Sep', 'Mon 28 Sep'].map((date) => ({ date, hash: 'no hash — Cycle A failed', cls: 'danger', result: '✕' })), { date: 'Fri 25 Sep', hash: '9c1e7a0d52f3b8e4…a2b4b07', cls: 'pos', result: '✓ 1/10' }]
        : [{ date: 'Fri 25 Sep', hash: '9c1e7a0d52f3b8e4…a2b4b07', cls: 'pos', result: '✓ 1/10' }, { date: 'Thu 24 Sep', hash: 'pre-ghost drill — not counted', cls: 'muted', result: '–' }],
      lastSha256: '9c1e7a0d52f3b8e4c6a19d07f2e85b3a4d6c1f90e7b25a83c4d9f0e16a2b4b07',
      replayNote: '✓ replay matches the ledgered twin (Fri 25 Sep)',
    },
    dataGate: {
      when: stale ? 'Cycle A · Thu 1 Oct 17:05 ET' : 'Cycle A · Fri 25 Sep 17:05 ET',
      tripped: stale ? 'Tripped 4 sessions' : null,
      checks: stale ? badChecks : okChecks,
      missing: stale ? { count: 317, total: 319, sample: ['GSAT', 'CORT', 'TXG', 'ROKU', 'HALO', 'TWST', 'MU', 'ORKA', 'AMD', 'KNSA', 'AAPL', 'MSFT'], note: 'The feed returned Friday’s bars for Monday–Thursday. Nothing trades on partial data; the day is skipped, never guessed.' } : null,
    },
    broker,
    heartbeats: [
      stale ? { step: 'cycle_a', expected: '17:05', last: 'Thu 17:05:44', duration: '38 s', status: 'Failed', dot: 'red', cls: 'danger' } : { step: 'cycle_a', expected: '17:05', last: 'Fri 17:06:19', duration: '41 s', status: 'OK', dot: 'ok', cls: 'pos' },
      sch('deadman', '18:15'), sch('cycle_submit', '19:15'), sch('cycle_submit (retry)', '19:45'), sch('deadman --submit', '21:30'),
      { step: 'cycle_b', expected: '09:50', last: stale ? 'Thu 09:51:02' : 'Fri 09:51:12', duration: '22 s', status: 'OK', dot: 'ok', cls: 'pos' },
      { step: 'rescreen', expected: '1st of quarter 10:00', last: 'Thu 1 Oct 10:00:41', duration: '2 m 10 s', status: 'OK', dot: 'ok', cls: 'pos' },
    ],
    indexer: { commit: '7f3c2a1', message: 'ledger: cycle_a 2026-09-25 (4 intents)', lag: ixDown ? '14 min · 3 commits behind' : '0 commits · 2 min', errors: ixDown ? '3 · connection refused' : '0', readModel: 'SQLite · 1,284 rows', down: ixDown, label: ixDown ? 'Down · 14 min' : 'In sync' },
  };
}

/* ───────── roadmap ───────── */

const TASK_DAYS: Record<string, number> = { G1: 2, G2: 2, G4: 3, G5: 6, G6: 14, P1: 28, P2: 28, P3: 35, P4: 36, S1: 35, S2: 35, X3: 35 };

export function roadmap(sc: Scenario): RoadmapPayload {
  const stale = sc.health === 'stale';
  const p1Open = alerts(sc).alerts.some((a) => a.priority === 'P1' && a.status === 'open');
  return {
    current: { ghost: 0, paper: 1, live: 4 }[sc.env],
    currentFailing: stale && sc.env === 'ghost',
    phases: [
      { n: '1', label: 'Ghost', dates: 'Mon 28 Sep → Fri 30 Oct 2026 · 25 sessions', gates: [{ ok: stale ? false : null, label: '10 consecutive deterministic sessions — 1 / 10' + (stale ? ', stalled' : '') }, { ok: !p1Open, label: 'Zero open P1 issues' }, { ok: true, label: 'Nightly rehearsal sends what the ledger says' }] },
      { n: '2', label: 'Paper', dates: 'from Mon 2 Nov 2026 · first week in approval mode', gates: [{ ok: null, label: '10 clean paper sessions (earliest Fri 13 Nov)' }, { ok: null, label: 'No P1 and no reconciliation break' }, { ok: null, label: 'Average slippage ≤ 10 bps/side' }] },
      { n: '3', label: 'Evaluation', dates: '2 Nov 2026 → Tue 4 May 2027 · 126 sessions · 2 adaptations', gates: [{ ok: null, label: 'Tracking error to twin < 0.5%/month' }, { ok: null, label: 'Slippage ≤ 10 bps/side' }, { ok: null, label: 'Rolling 63-session Sharpe > 0.5 absent a bear market' }, { ok: null, label: 'Zero unresolved P1' }] },
      { n: '4', label: 'Private build', dates: 'Jan 2027 build · burn-in Mon 1 Feb → Mon 1 Mar 2027', gates: [{ ok: null, label: '20 sessions where the private twin equals the public twin' }] },
      { n: '5', label: 'Real money', dates: 'pilot from Mon 10 May 2027 at the earliest', gates: [{ ok: null, label: 'Evaluation passed and burn-in passed' }, { ok: null, label: 'Decisions D1–D8 made' }, { ok: null, label: 'Tasks R1–R5 done' }] },
    ],
    decisions: sample.decisions.map((d) => ({ id: d.id, title: d.t, recommendation: d.r, due: d.due, daysLeft: d.days, status: d.st as 'Open' | 'Recommended' })),
    tasks: sample.tasks.map((t) => ({ group: t.group, id: t.id, task: t.task, owner: t.owner, due: t.due, status: t.status as RoadmapPayload['tasks'][number]['status'], daysLeft: TASK_DAYS[t.id] ?? null })),
  };
}

/** Every payload of one scenario, keyed for convenience in tests. */
export function snapshot(sc: Scenario = defaultScenario()) {
  return {
    overview: overview(sc),
    holdings: holdings(sc),
    pending: pending(sc),
    history: history(sc),
    roundTrips: roundTrips(sc),
    alerts: alerts(sc),
    compliance: compliance(),
    health: health(sc),
    roadmap: roadmap(sc),
  };
}

/* ───────── holding detail ───────── */


const HOLIDAYS = new Set(['2026-09-07', '2026-07-03', '2026-06-19', '2026-05-25', '2026-04-03']);

/** Illustrative price path that passes through the real avg cost and last close. */
export function holdingDetail(sc: Scenario, symbol: string): HoldingDetailPayload | null {
  const h = holdings(sc).positions.find((x) => x.symbol === symbol);
  if (!h) return null;
  const N = 260;
  const r = rng(seed(h.symbol));
  const vol = (h.atr / h.last) * 0.6;
  const p = [100];
  for (let i = 1; i < N; i++) p.push(p[i - 1] * (1 + (r() - 0.46) * vol * 1.8));
  const ei = N - h.heldSessions;
  const a = Math.log(h.avgCost / p[ei]);
  const b = Math.log(h.last / p[N - 1]);
  const closes = p.map((v, i) => v * Math.exp(i <= ei ? a : a + ((b - a) * (i - ei)) / (N - 1 - ei)));
  const dates = sessionsEndingAt(sample.asof, N, HOLIDAYS);
  const k = h.confidence;
  const tot = Math.round(k.signal * 0.4 + k.riskRoom * 0.3 + k.regime * 0.2 + (sc.health === 'stale' ? 15 : k.data) * 0.1);
  const n = Math.max(h.heldSessions, 3);
  const rc = rng(seed(h.symbol + 'c'));
  const hist: number[] = [];
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    hist.push(Math.max(0, Math.min(100, k.atEntry + (tot - k.atEntry) * t + (i && i < n - 1 ? (rc() - 0.5) * 8 : 0))));
  }
  return {
    symbol,
    prices: dates.map((date, i) => ({ date, close: +closes[i].toFixed(2) })),
    confidenceHistory: hist.map((v) => +v.toFixed(1)),
    lots: [{ opened: h.entryDate, shares: h.shares, cost: h.avgCost }],
  };
}
