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
  dayPct: number;
  entryDate: string;
  heldSessions: number;
  atr: number;
  high: number;
  rank: number;
  offHighPct: number;
  smaStack: string;
  /** avg − STOP_ATR × ATR */
  initialStop: number;
  /** 52-week-high − TRAIL_ATR × ATR */
  trailingStop: number;
  confidence: Confidence;
  crossSource: 'agree' | 'unavailable' | 'disagree';
  debtPct: number;
  cashPct: number;
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
  lots: Lot[];
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
  decisionClose: number;
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

export type ExitReason = 'stop' | 'trail' | 'rank' | 'time' | 'sma' | 'forced' | 'manual';

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
  confAtEntry: number;
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
  debtPct: number;
  cashPct: number;
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
