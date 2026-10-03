// API v1 payloads (docs/08 §10). The console API builds these from the read
// model; in mock mode MSW serves them from the prototype fixtures. Dates are
// ISO `YYYY-MM-DD`; the UI formats them. Display copy lives in the selectors.

export type Env = 'ghost' | 'paper' | 'live';
export type TradingState = 'running' | 'paused' | 'held' | 'halted' | 'stopped';
export type Role = 'owner' | 'viewer';
/** Server-side data health. `loading` is never sent; the client derives it. */
export type DataHealth = 'loaded' | 'empty' | 'stale' | 'error';
export type Side = 'BUY' | 'SELL';

export interface Clock {
  /** ET session label, e.g. "Fri 25 Sep" */
  d: string;
  /** ET time, e.g. "18:03 ET" */
  t: string;
}

export interface SystemStatus {
  env: Env;
  health: DataHealth;
  trading: TradingState;
  /** Tonight's held night was released (approval mode). */
  released: boolean;
  haltCleared: boolean;
  /** When the kill switch was set, e.g. "18:04 ET". */
  stopAt: string | null;
  /** A stop-and-flatten is queued for the next open. */
  flatten: boolean;
  clock: Clock;
  facts: Facts;
}

/**
 * Dated facts the chrome and banners quote. The server derives them from the
 * ledger and the exchange calendar so no copy hard-codes a date.
 */
export interface Facts {
  /** Today's date in ET (ISO). */
  today: string;
  model: {
    /** Session the Model book (the twin) is valued at. */
    asof: string;
    /** ET time the last good Cycle A finished, e.g. "17:05 ET". */
    builtAt: string | null;
    /** Minutes since that Cycle A finished. */
    ageMin: number | null;
    /** Completed sessions after `asof` that have no good Cycle A. */
    sessionsBehind: number;
  };
  /** The latest Cycle A run. */
  lastCycleA: { session: string; ok: boolean; finishedAt: string | null; durationS: number | null } | null;
  /** Consecutive failed Cycle A sessions, newest last. */
  failing: { count: number; from: string; to: string; reason: string; checks: string } | null;
  /** Next regular session (ISO), where orders would fill at the open. */
  nextOpen: string;
  /** Minutes until tonight's 19:15 ET submit, when still ahead. */
  submitInMin: number | null;
  /** Minutes until the next 09:30 ET open. */
  openInMin: number | null;
  ledger: { commit: string | null; syncedMinAgo: number | null; down: boolean; downMin: number | null };
  broker: { reachable: boolean; lastOk: string | null; latencyMs: number | null } | null;
  /** ET time of the last account snapshot (paper/live only). */
  accountAt: string | null;
  halt: { symbol: string; expected: number; actual: number; at: string } | null;
  screen: { last: string; next: string };
  /** Owner decision D1 (written Sharia policy) due date. */
  d1Due: string;
  /** First paper session (docs/07). */
  paperStart: string;
  twinStart: string;
  /** One-line market backdrop from the agent's journal, or null. */
  regime: string | null;
}

export interface ManualOrder {
  symbol: string;
  shares: number;
  pct: number;
}

/** controls.json v2 (docs/08 §7.2), as the console reads it. */
export interface ControlsState {
  lockedSymbols: string[];
  /** Held names excluded by an owner ruling: a forced exit is queued. */
  forcedExits: string[];
  manualOrders: ManualOrder[];
  /** Explicit owner and re-screen exclusions shown as chips (the +N rest are summarised). */
  excludedSymbols: string[];
  excludedMore: number;
  grossCap: number | null;
  pauseAdapt: boolean;
}

export interface Me {
  user: string;
  role: Role;
}

export interface EquityPoint {
  date: string;
  model: number;
  account: number | null;
  benchmark: number;
}

export interface PhaseInfo {
  n: number;
  of: number;
  title: string;
  gate: string;
  dates: string;
  decision: string;
}

/** Chart marker: ◆ adaptation, ⚑ override, ■ halt. */
export interface EquityMarker {
  date: string;
  kind: 'adaptation' | 'override' | 'halt';
  text: string;
}

export interface OverviewPayload {
  system: SystemStatus;
  controls: ControlsState;
  me: Me;
  asof: string;
  twinStart: string;
  startCapital: number;
  equity: number;
  cash: number;
  accountCash: number | null;
  equityCurve: EquityPoint[];
  markers: EquityMarker[];
  phase: PhaseInfo;
}

export interface Confidence {
  signal: number;
  riskRoom: number;
  regime: number;
  data: number;
  atEntry: number;
}

export interface Dividend {
  perShare: number;
  shares: number;
  payDate: string;
}

export interface Position {
  symbol: string;
  name: string;
  sector: string;
  industry: string;
  shares: number;
  avgCost: number;
  last: number;
  /** Change since the previous session's close, % — null without a previous price. */
  dayPct: number | null;
  entryDate: string;
  heldSessions: number;
  /** Average true range in $ (from the insights step, M3). */
  atr: number | null;
  /** 52-week high. */
  high: number | null;
  /** Momentum rank in the universe today. */
  rank: number | null;
  offHighPct: number | null;
  smaStack: string | null;
  /** avg − STOP_ATR × ATR */
  initialStop: number | null;
  /** 52-week-high − TRAIL_ATR × ATR */
  trailingStop: number | null;
  /** null until ledger/insights/<asof>.json exists (docs/08 §6, milestone M3). */
  confidence: Confidence | null;
  crossSource: 'agree' | 'unavailable' | 'disagree' | null;
  /** Debt and cash vs market cap, % (null when the screen has no figure). */
  debtPct: number | null;
  cashPct: number | null;
  /** Date of the screen the ratios come from. */
  screenedOn: string | null;
  /** Review-flagged by the business screen; owner ruling pending (D1). */
  review: { keyword: string; category: string } | null;
  entryReason: string;
  rankExit: boolean;
  nextDividend: Dividend | null;
  account: AccountLeg | null;
}

/** The broker side of a position (Account book). */
export interface AccountLeg {
  shares: number;
  avgCost: number;
  slippageBps: number;
  /** Why the account differs from the Model, when it does. */
  drift: { row: string; short: string; detail: string } | null;
}

export interface HoldingsPayload {
  asof: string;
  positions: Position[];
  /** Names the account holds that the Model does not (paper/live). */
  accountOnly?: { symbol: string; shares: number; avgCost: number; last: number }[];
}

export interface Lot {
  opened: string;
  shares: number;
  cost: number;
}

/** GET /api/holdings/{sym}: chart series and history for the drawer. */
export interface HoldingDetailPayload {
  symbol: string;
  /** Daily closes, oldest first (≥ 200 sessions for the SMAs). */
  prices: { date: string; close: number }[];
  /** Overall confidence per session since entry, oldest first. */
  confidenceHistory: number[];
  /** Why `prices` is empty, when it is. */
  pricesNote: string | null;
  lots: Lot[];
  /** OOS share of trades won per confidence band ([] until live/calibration.py has run). */
  calibration: { band: 'high' | 'med' | 'low'; n: number; wonRate: number | null }[];
}

export type IntentSource = 'agent' | 'forced' | 'manual';

export interface Intent {
  id: string;
  symbol: string;
  name: string;
  side: Side;
  shares: number;
  /** "24 sh", "39 sh (all)" */
  qtyLabel: string;
  /** "$3,400 → 24 sh" for buys sized in dollars */
  amountLabel: string;
  refClose: number;
  estValue: number;
  reason: string;
  source: IntentSource;
  guardrail: string | null;
  guardrailNote: string;
  clientOrderId: string;
  /** Part of a stop-and-flatten. */
  flatten?: boolean;
}

export interface PendingPayload {
  asof: string;
  nextOpen: string;
  intents: Intent[];
}

export interface HistOrder {
  id: string;
  decisionDate: string;
  fillDate: string;
  symbol: string;
  side: Side;
  shares: number;
  /** Account shares when the submit adjusted the order (F6). */
  accountShares: number | null;
  /** Close the decision was made at (null in Ghost: the twin does not ledger it). */
  decisionClose: number | null;
  officialOpen: number;
  fillPrice: number;
  fees: number;
  realized: number | null;
  heldDays: number | null;
  reason: string;
}

export interface HistoryPayload {
  since: string;
  total: number;
  feesSinceStart: number;
  orders: HistOrder[];
}

export type ExitReason = 'stop' | 'trail' | 'rank' | 'time' | 'sma' | 'derisk' | 'forced' | 'manual' | 'other';

export interface RoundTrip {
  symbol: string;
  sector: string;
  entryDate: string;
  exitDate: string;
  days: number;
  entryPrice: number;
  exitPrice: number;
  pnl: number;
  exitReason: ExitReason;
  /** Confidence at entry (null before the insights step, M3). */
  confAtEntry: number | null;
  /** The ledger's own wording of the exit. */
  reason: string;
}

export interface RoundTripsPayload {
  fees: number;
  trips: RoundTrip[];
}

export type Grade = 'A' | 'B' | 'C' | 'F';

export interface UniverseName {
  symbol: string;
  name: string;
  grade: Grade;
  status: 'Compliant' | 'Under review' | 'Excluded';
  debtPct: number | null;
  cashPct: number | null;
  flag: string;
}

export interface Rescreen {
  id: string;
  date: string;
  kind: string;
  file: string;
  dot: 'ok' | 'warn' | 'info';
  summary: string;
  stats: { l: string; v: string; cls: string }[];
  outTitle: string;
  out: { symbol: string; reason: string }[];
  outTag: string;
  inTitle: string;
  in: string[];
  inNote: string;
  note: string;
  noteCls: string;
}

export interface CompliancePayload {
  screenedOn: string;
  nextScreen: string;
  universeSize: number;
  reviewFlagged: number;
  excludedAfterRescreen: number;
  universe: UniverseName[];
  rescreens: Rescreen[];
}

export type Priority = 'P1' | 'P2';
export type AlertStatus = 'open' | 'acknowledged' | 'resolved';

export interface Alert {
  id: string;
  priority: Priority;
  title: string;
  detail: string;
  source: string;
  githubIssue: string | null;
  raisedAt: string;
  status: AlertStatus;
  note: string;
}

export interface AlertsPayload {
  alerts: Alert[];
}

export type CellStatus = 'ok' | 'fail' | 'held' | 'skip';

export interface HealthCheck {
  ok: boolean | null;
  label: string;
  value: string;
  min: string;
}

export interface HealthPayload {
  summary: string;
  degraded: boolean;
  sessions: { dow: string; label: string }[];
  cycles: { A: CellStatus[]; S: CellStatus[]; B: CellStatus[] };
  /** Raw cycle records keyed "<A|S|B><index>" */
  records: Record<string, unknown>;
  defaultCell: string;
  gate: {
    streak: number;
    target: number;
    stalled: string | null;
    earliestPass: string;
    hashes: { date: string; hash: string; cls: string; result: string }[];
    lastSha256: string;
    replayNote: string;
  };
  dataGate: {
    when: string;
    tripped: string | null;
    checks: HealthCheck[];
    missing: { count: number; total: number; sample: string[]; note: string } | null;
  };
  broker: { k: string; v: string; cls: string }[];
  heartbeats: { step: string; expected: string; last: string; duration: string; status: string; dot: string; cls: string }[];
  indexer: { commit: string; message: string; lag: string; errors: string; readModel: string; down: boolean; label: string };
}

export interface Decision {
  id: string;
  title: string;
  recommendation: string;
  due: string;
  daysLeft: number | null;
  status: 'Open' | 'Recommended';
}

export interface Task {
  group: string;
  id: string;
  task: string;
  owner: string;
  due: string;
  status: 'done' | 'open' | 'conditional' | 'option';
  daysLeft: number | null;
}

export interface RoadmapPhase {
  n: string;
  label: string;
  dates: string;
  gates: { ok: boolean | null; label: string }[];
}

export interface RoadmapPayload {
  current: number;
  currentFailing: boolean;
  phases: RoadmapPhase[];
  decisions: Decision[];
  tasks: Task[];
}

/* ───────── M1: auth and controls ───────── */

export interface MePayload {
  user: string;
  role: Role;
  csrf: string;
  /** false when the server runs with CONSOLE_AUTH=off (development). */
  auth: boolean;
  totpAgeS: number | null;
}

export interface ControlsDoc {
  version: number;
  kill: boolean;
  pause_entries: boolean;
  excluded_symbols: string[];
  gross_cap: number | null;
  locked_symbols: string[];
  manual_orders: { id: string; symbol: string; side: 'buy' | 'sell'; qty: number | null; fraction: number | null; reason: string; expires: string }[];
  pause_adapt: boolean;
  pause_adapt_since: string | null;
  allow_manual_buys: boolean;
}

export interface ControlsPayload {
  controls: ControlsDoc;
  pending: { what: string; eff: string; sha: string; when: string }[];
  /** git | github | dry */
  write: string;
  dispatch: boolean;
  gateway: boolean;
  halt: { halted?: boolean; since?: string; reason?: string; diffs?: { symbol: string; expected: number; actual: number }[] } | null;
  heldNight: boolean;
  exposure: number;
  drawdown: number;
  limits: Record<string, number | null>;
}

export interface OrderLine {
  side: 'buy' | 'sell';
  sideL: string;
  s: string;
  q: string;
  v: string;
  tag: string;
}

export interface Preview {
  action: string;
  title: string;
  sub: string;
  danger: boolean;
  verb: string;
  eff: string;
  effS: string;
  rows: { k: string; a: string; b: string }[];
  added: OrderLine[];
  blocked: OrderLine[];
  canceled: OrderLine[];
  proceeds: string;
  pnl: string;
  drift: string;
  fid: string;
  word: string | null;
  errors: string[];
  pending: string;
  steps: string[];
  previewHash: string;
}

export interface ApplyResult {
  applied: boolean;
  steps: { l: string; st: 'ok' | 'fail' | 'skip' }[];
  sha: string | null;
  actionId: string;
  title: string;
  eff: string;
  pending: string;
}

export interface PreflightPayload {
  checks: { id: string; l: string; s: 'pass' | 'fail' | 'man'; d: string; note?: boolean; fix?: boolean; pass: boolean }[];
  ok: boolean;
  n: number;
}

export interface AuditRow {
  t: string;
  at: string;
  actor: string;
  act: string;
  ba: string;
  reason: string;
  eff: string;
  sha: string;
  res: string;
}

export interface AuditPayload {
  rows: AuditRow[];
  logins: { at: string; user: string; event: string; detail: string }[];
}

/* ───────── M2/M3: performance and agent ───────── */

export interface MetricRow {
  key: string;
  label: string;
  note: string;
  unit: 'pct' | 'ratio' | 'count';
  model: number | null;
  account: number | null;
  bench: number | null;
  ref: number | null;
}

export interface PerformancePayload {
  since: string;
  sessions: number;
  metrics: MetricRow[];
  monthly: { label: string; live: boolean; months: (number | null)[]; year: number }[];
  periods: Record<'today' | 'wtd' | 'mtd' | 'all', { pnl: number; pct: number }>;
  byHolding: { label: string; value: number }[];
  bySector: { label: string; value: number }[];
  gap: { label: string; value: number }[] | null;
  execution: { fills: { date: string; symbol: string; side: string; bps: number }[]; avgBps: number | null; outliers: number; missed: number; trackingError: { month: string; value: number }[] } | null;
  dividends: { gross: number; withholding: number };
  reference: { sharpe: number | null; mdd: number | null; cagr: number | null; total: number | null; calmar: number | null; trades: number | null; window: string[] | null };
}

export interface CalibrationBand {
  band: 'high' | 'med' | 'low';
  n: number;
  hit_rate: number | null;
  avg_return: number | null;
  trade_won_rate?: number | null;
}

export interface AgentPayload {
  handle: string;
  freezeCommit: string | null;
  params: { k: string; v: number | null; lo: number; hi: number; frozen: number | null }[];
  regime: { score?: number; ixic_vs_sma200?: number; ixic_vs_sma50?: number; breadth?: number; mood?: string };
  mood: string | null;
  sentiment: { date: string; s: number }[];
  journal: { date: string; mood: string; sentiment: number; note: string }[];
  adaptations: { date: string; changes: Record<string, number>; note: string; live: boolean }[];
  oosAdaptations: { date: string; changes: Record<string, number>; note: string }[];
  nextAdapt: string | null;
  adaptEvery: number;
  sessions: number;
  adaptPaused: boolean;
  adaptPausedSince: string | null;
  calibration: { window: string[]; horizon_sessions: number; position_days: number; round_trips: number; method: string; bands: CalibrationBand[] } | null;
  liveBands: { band: 'high' | 'med' | 'low'; n: number; hit: number | null; ret: number | null }[];
}
