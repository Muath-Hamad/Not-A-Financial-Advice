// Mock M1–M3 endpoints: auth, controls (preview → apply), preflight, audit,
// performance and agent. The real server derives all of this from the ledger;
// here it is built from the prototype fixtures so every frame renders offline.
// Illustrative only — never seed production with this file.

import sample from './sample-data.json';
import * as S from './scenario';
import type {
  AgentPayload, ApplyResult, AuditPayload, AuditRow, ControlsPayload, MePayload, OrderLine, PerformancePayload, PreflightPayload, Preview,
} from '@/api/types';
import type { ControlAction } from '@/domain/actions';

type Sc = S.Scenario;

export function me(sc: Sc): MePayload {
  return { user: sc.role === 'owner' ? 'owner' : 'reviewer', role: sc.role, csrf: 'mock-csrf', auth: true, totpAgeS: 240 };
}

export function controls(sc: Sc): ControlsPayload {
  const c = sc.controls;
  const ks = c.forcedExits;
  return {
    controls: {
      version: 2,
      kill: sc.trading === 'stopped',
      pause_entries: sc.trading === 'paused',
      excluded_symbols: [...c.excludedSymbols, ...ks],
      gross_cap: c.grossCap == null ? null : c.grossCap / 100,
      locked_symbols: c.lockedSymbols,
      manual_orders: c.manualOrders.map((m) => ({ id: 'm-' + m.symbol, symbol: m.symbol, side: 'sell', qty: m.shares, fraction: null, reason: 'trim', expires: '2026-09-28' })),
      pause_adapt: c.pauseAdapt,
      pause_adapt_since: c.pauseAdapt ? '2026-09-25' : null,
      allow_manual_buys: false,
    },
    pending: [
      ...(sc.trading === 'paused' ? [{ what: 'pause_entries = true', eff: 'Tonight’s 19:15 ET submit', sha: '4b1c9e2', when: '18:04 ET' }] : []),
      ...c.lockedSymbols.map((s) => ({ what: 'locked_symbols += ' + s, eff: 'Tonight’s 19:15 ET submit', sha: '8e0f3a7', when: '18:05 ET' })),
      ...c.manualOrders.map((m) => ({ what: 'manual_orders += SELL ' + m.shares + ' ' + m.symbol, eff: 'Tonight’s 19:15 ET submit', sha: '3d7a2c0', when: '18:06 ET' })),
    ],
    write: 'git',
    dispatch: true,
    gateway: sc.env !== 'ghost',
    halt: sc.trading === 'halted' && !sc.haltCleared ? { halted: true, since: '2026-09-28', reason: 'reconciliation break', diffs: [{ symbol: 'ROKU', expected: 75, actual: 74 }] } : null,
    heldNight: sc.trading === 'held' && !sc.released,
    exposure: 94.8,
    drawdown: -11.2,
    limits: { MAX_POS_WEIGHT: 0.18, MAX_DAILY_TURNOVER: 0.6, ADV_CAP: 0.01, KILL_DD_LIMIT: -0.25 },
  };
}

const money = (v: number) => (v < 0 ? '−' : '') + '$' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function intentsOf(sc: Sc) {
  return S.pending(sc).intents.filter((o) => !o.guardrail);
}

const oi = (o: { side: string; symbol: string; qtyLabel: string; estValue: number }, tag: string): OrderLine => ({
  side: o.side === 'BUY' ? 'buy' : 'sell', sideL: o.side, s: o.symbol, q: o.qtyLabel, v: money(o.estValue), tag,
});

const STATE: Record<Sc['trading'], string> = { running: 'RUNNING', paused: 'ENTRIES PAUSED', held: 'NIGHT HELD', halted: 'HALTED', stopped: 'STOPPED' };

export function preview(sc: Sc, action: ControlAction, p: Record<string, unknown>): Preview {
  const book = S.holdings(sc).positions;
  const sym = typeof p.symbol === 'string' ? p.symbol.toUpperCase() : null;
  const h = sym ? book.find((x) => x.symbol === sym) : undefined;
  const live = intentsOf(sc);
  const st = STATE[sc.trading];
  const base: Preview = {
    action, title: action, sub: '', danger: false, verb: 'Confirm', eff: 'Tonight’s 19:15 ET submit', effS: 'Tonight 19:15 ET', rows: [], added: [], blocked: [], canceled: [],
    proceeds: '— no positions are sold', pnl: '$0.00 locked in', drift: 'None', fid: '', word: null, errors: [], pending: '', steps: [], previewHash: 'mock-' + action + JSON.stringify(p),
  };
  const steps = ['Validate against the controls.json v2 schema', 'Commit to the ledger', 'Push to origin'];
  switch (action) {
    case 'stop':
      return { ...base, title: 'STOP TRADING', sub: 'Kill switch. Cancels open orders now and freezes every later cycle.', danger: true, verb: 'STOP TRADING', eff: 'Immediate — open orders canceled now; every cycle frozen until you resume', effS: 'Immediate',
        rows: [{ k: 'Trading state', a: st, b: 'STOPPED (kill)' }, { k: 'controls.kill', a: 'false', b: 'true' }, { k: 'Next submit', a: live.length + ' orders', b: 'nothing sent' }],
        canceled: live.map((o) => oi(o, 'cancel')), drift: 'The account freezes while the Model keeps trading; drift grows each session',
        fid: 'Trading halts; the twin keeps running for comparison. Every stopped session widens the gap to the evaluated record.', word: 'STOP', pending: 'kill = true · read by every cycle until resumed',
        steps: [...steps, 'Cancel open orders at the broker'] };
    case 'flatten': {
      const proceeds = book.reduce((a, x) => a + x.shares * x.last, 0);
      const pnl = book.reduce((a, x) => a + (x.last - x.avgCost) * x.shares, 0);
      return { ...base, title: 'Stop & flatten', sub: 'Kill switch plus a market-on-open sell of every position.', danger: true, verb: 'STOP & FLATTEN', eff: 'Kill: immediate · sells: Mon 28 Sep 09:30 ET open', effS: 'Immediate + next open',
        rows: [{ k: 'Trading state', a: st, b: 'STOPPED + FLATTEN' }, { k: 'Positions', a: book.length + ' names', b: '0 names · 100% cash' }],
        added: book.map((x) => ({ side: 'sell', sideL: 'SELL', s: x.symbol, q: x.shares + ' sh', v: money(x.shares * x.last), tag: 'flatten' })), canceled: live.map((o) => oi(o, 'cancel')),
        proceeds: money(proceeds) + ' at last close, before slippage', pnl: (pnl >= 0 ? '+' : '') + money(pnl) + ' unrealized becomes realized', drift: 'Account 0% invested vs the Model — maximum drift',
        fid: 'Large deviation: the account leaves the evaluated path entirely. Typing FLATTEN is required.', word: 'FLATTEN', pending: 'kill = true · flatten ' + book.length + ' positions at the open',
        steps: [...steps, 'Cancel open orders at the broker', 'Queue market-on-open sells'] };
    }
    case 'pause': {
      const buys = live.filter((o) => o.side === 'BUY' && o.source === 'agent');
      return { ...base, title: 'Pause entries', sub: 'Blocks new buys. Sells, stops and forced exits still flow.', verb: 'Pause entries',
        errors: sc.trading === 'paused' ? ['entries are already paused'] : [],
        rows: [{ k: 'controls.pause_entries', a: 'false', b: 'true' }, { k: 'Trading state', a: st, b: 'ENTRIES PAUSED' }],
        blocked: buys.map((o) => oi(o, 'pause_entries')), drift: money(buys.reduce((a, o) => a + o.estValue, 0)) + ' more cash in the account than the Model',
        fid: 'Declared deviation: labelled "explained" in the drift report, not a breach.', pending: 'pause_entries = true', steps };
    }
    case 'resume_entries':
      return { ...base, title: 'Resume entries', sub: 'Lets the agent open new positions again.', verb: 'Resume entries', rows: [{ k: 'controls.pause_entries', a: 'true', b: 'false' }, { k: 'Trading state', a: st, b: 'RUNNING' }], drift: 'Returns toward the Model', pending: 'pause_entries = false', steps };
    case 'resume':
      return { ...base, title: 'Resume trading', sub: 'Clears the kill switch after the preflight checklist.', verb: 'Resume trading', eff: 'Next Cycle A, Mon 28 Sep 17:05 ET', effS: 'Next Cycle A', rows: [{ k: 'controls.kill', a: 'true', b: 'false' }, { k: 'Trading state', a: st, b: 'RUNNING' }], drift: 'Returns toward the Model from the next submit', pending: 'kill = false', steps };
    case 'release':
      return { ...base, title: 'Release tonight’s submission', sub: 'Runs the held submit with --approved.', verb: 'Release', eff: 'Immediate — submit runs now', effS: 'Immediate', rows: [{ k: 'Night', a: 'HELD', b: 'RELEASED' }], added: live.map((o) => oi(o, 'release')), pending: 'submit --approved dispatched', steps: ['Dispatch live-submit with --approved', 'Wait for the run to start'] };
    case 'clear_halt':
      return { ...base, title: 'Clear the reconciliation halt', sub: 'Writes the cause into ledger/halt.json and lets the submit run again.', verb: 'Clear halt', eff: 'Tonight’s 19:15 ET submit', rows: [{ k: 'halt.json · halted', a: 'true', b: 'false' }, { k: 'Cause', a: '—', b: String(p.cause ?? '').slice(0, 60) }], pending: 'halted = false', steps };
    case 'lock': case 'unlock': {
      const on = action === 'lock';
      return { ...base, title: (on ? 'Lock ' : 'Unlock ') + (sym ?? '—'), sub: on ? 'The agent skips this name: no buys, no sells (except a Sharia exit).' : 'Hands the name back to the agent.', verb: on ? 'Lock' : 'Unlock',
        errors: !h ? [(sym ?? 'symbol') + ' is not held'] : [], rows: [{ k: 'locked_symbols', a: on ? '—' : sym ?? '—', b: on ? '+ ' + sym : '—' }],
        blocked: on ? live.filter((o) => o.symbol === sym).map((o) => oi(o, 'locked')) : [], drift: on ? 'Follows the Model only if the agent would have held anyway' : 'Returns toward the Model', pending: 'locked_symbols ' + (on ? '+= ' : '-= ') + sym, steps };
    }
    case 'trim': {
      const pct = Number(p.pct ?? 50);
      const q = h ? Math.max(1, Math.floor((h.shares * pct) / 100)) : 0;
      return { ...base, title: 'Trim ' + (sym ?? '—') + ' by ' + pct + '%', sub: 'A manual sell at the next open; the rest stays agent-managed.', verb: 'Queue trim', danger: false, word: sym,
        errors: !h ? [(sym ?? 'symbol') + ' is not held'] : [], rows: h ? [{ k: sym + ' shares', a: String(h.shares), b: String(h.shares - q) }] : [],
        added: h ? [{ side: 'sell', sideL: 'SELL', s: h.symbol, q: q + ' sh', v: money(q * h.last), tag: 'manual' }] : [],
        proceeds: h ? money(q * h.last) + ' at last close' : '—', pnl: h ? money((h.last - h.avgCost) * q) + ' realized' : '—', drift: 'Account holds less ' + sym + ' than the Model', fid: 'Manual order: a declared deviation, labelled in the drift report.', pending: 'manual_orders += SELL ' + q + ' ' + sym, steps };
    }
    case 'force_exit':
      return { ...base, title: 'Force exit ' + (sym ?? '—'), sub: 'Adds the name to excluded_symbols: sold at the next open and never bought back.', danger: true, verb: 'Force exit', word: sym,
        errors: !h ? [(sym ?? 'symbol') + ' is not held'] : [], rows: [{ k: 'excluded_symbols', a: S.defaultControls().excludedSymbols.length + 23 + ' names', b: '+ ' + sym }],
        added: h ? [{ side: 'sell', sideL: 'SELL', s: h.symbol, q: h.shares + ' sh (all)', v: money(h.shares * h.last), tag: 'forced' }] : [],
        proceeds: h ? money(h.shares * h.last) + ' at last close' : '—', pnl: h ? money((h.last - h.avgCost) * h.shares) + ' realized' : '—', drift: 'Model and account both exit — no drift', pending: 'excluded_symbols += ' + sym + ' (forced exit)', steps };
    case 'unexclude':
      return { ...base, title: 'Remove ' + (sym ?? '—') + ' from exclusions', sub: 'The agent may buy it again if it ranks.', verb: 'Remove', rows: [{ k: 'excluded_symbols', a: sym ?? '—', b: '—' }], pending: 'excluded_symbols -= ' + sym, steps };
    case 'cancel_manual':
      return { ...base, title: 'Cancel the manual order for ' + (sym ?? '—'), sub: 'Removes it from the queue before the submit.', verb: 'Cancel order', rows: [{ k: 'manual_orders', a: '1 queued', b: '0' }], pending: 'manual_orders -= ' + p.id, steps };
    case 'gross': {
      const cap = p.cap == null ? null : Number(p.cap);
      return { ...base, title: cap == null ? 'Remove the gross cap' : 'Gross exposure cap ' + cap + '%', sub: 'Caps how much of the portfolio the agent may invest.', verb: 'Apply cap', eff: 'Next Cycle A, Mon 28 Sep 17:05 ET', effS: 'Next Cycle A',
        rows: [{ k: 'controls.gross_cap', a: sc.controls.grossCap == null ? 'off' : sc.controls.grossCap + '%', b: cap == null ? 'off' : cap + '%' }], drift: cap != null && cap < 95 ? 'Account up to ' + (95 - cap) + ' pp less invested than the Model' : 'None', pending: 'gross_cap = ' + (cap == null ? 'null' : cap / 100), steps };
    }
    case 'adapt': {
      const on = !sc.controls.pauseAdapt;
      return { ...base, title: on ? 'Pause adapt()' : 'Resume adapt()', sub: on ? 'Freezes the agent’s parameters at their current values.' : 'Lets adapt() re-tune every 63 sessions again.', verb: on ? 'Pause adapt()' : 'Resume adapt()', eff: 'Next Cycle A, Mon 28 Sep 17:05 ET', effS: 'Next Cycle A',
        rows: [{ k: 'controls.pause_adapt', a: String(!on), b: String(on) }], word: on ? 'PAUSE' : null, fid: on ? 'Pausing changes the twin path and ends comparability with the frozen OOS record.' : '', pending: 'pause_adapt = ' + on, steps };
    }
    case 'rerun':
      return { ...base, title: 'Re-run ' + String(p.step ?? 'Cycle A'), sub: 'Dispatches the workflow now. Steps are idempotent.', verb: 'Re-run', eff: 'Immediate — the workflow starts in about a minute', effS: 'Immediate', rows: [{ k: 'Workflow', a: '—', b: String(p.step ?? 'Cycle A') }], pending: 'workflow_dispatch sent', steps: ['Dispatch the workflow'] };
    default:
      return { ...base, errors: ['unknown action'] };
  }
}

/** The state change a successful mock apply makes. */
export function applyPatch(sc: Sc, action: ControlAction, p: Record<string, unknown>): Partial<Sc> {
  const c = { ...sc.controls };
  const sym = typeof p.symbol === 'string' ? p.symbol.toUpperCase() : '';
  switch (action) {
    case 'stop': case 'flatten': return { trading: 'stopped' };
    case 'pause': return { trading: 'paused' };
    case 'resume_entries': case 'resume': return { trading: 'running' };
    case 'release': return { released: true, trading: 'running' };
    case 'clear_halt': return { haltCleared: true, trading: 'running' };
    case 'lock': return { controls: { ...c, lockedSymbols: [...c.lockedSymbols, sym] } };
    case 'unlock': return { controls: { ...c, lockedSymbols: c.lockedSymbols.filter((s) => s !== sym) } };
    case 'force_exit': return { controls: { ...c, forcedExits: [...c.forcedExits, sym] } };
    case 'unexclude': return { controls: { ...c, excludedSymbols: c.excludedSymbols.filter((s) => s !== sym), forcedExits: c.forcedExits.filter((s) => s !== sym) } };
    case 'trim': {
      const h = S.holdings(sc).positions.find((x) => x.symbol === sym);
      const q = h ? Math.max(1, Math.floor((h.shares * Number(p.pct ?? 50)) / 100)) : 0;
      return { controls: { ...c, manualOrders: [...c.manualOrders, { symbol: sym, shares: q, pct: Number(p.pct ?? 50) }] } };
    }
    case 'cancel_manual': return { controls: { ...c, manualOrders: c.manualOrders.filter((m) => m.symbol !== sym) } };
    case 'gross': return { controls: { ...c, grossCap: p.cap == null ? null : Number(p.cap) } };
    case 'adapt': return { controls: { ...c, pauseAdapt: !c.pauseAdapt } };
    default: return {};
  }
}

export function applyResult(pv: Preview, ok: boolean): ApplyResult {
  const steps = pv.steps.map((l, i) => ({ l, st: (ok || i < pv.steps.length - 1 ? 'ok' : 'fail') as 'ok' | 'fail' }));
  return { applied: ok, steps, sha: ok ? '9a4e1c7d2b' : null, actionId: 'mock-' + pv.action, title: pv.title, eff: pv.eff, pending: ok ? pv.pending : '' };
}

export function preflight(sc: Sc, ticks: Record<string, boolean>, note: string): PreflightPayload {
  const p1 = S.alerts(sc).alerts.filter((a) => a.priority === 'P1' && a.status === 'open');
  const aOk = sc.health !== 'stale';
  const checks: PreflightPayload['checks'] = [
    { id: 'halt', l: 'No reconciliation halt', s: sc.trading === 'halted' && !sc.haltCleared ? 'fail' : 'pass', d: 'ledger/halt.json · halted: ' + (sc.trading === 'halted' && !sc.haltCleared), pass: false },
    { id: 'recon', l: 'Last reconciliation OK', s: 'pass', d: 'Cycle B Fri 25 Sep · ok', pass: false },
    { id: 'cyca', l: 'Last Cycle A OK — or acknowledged with a note', s: aOk ? 'pass' : 'man', note: !aOk, d: aOk ? 'ok' : 'Failed Thu 1 Oct — data gate: coverage at asof 0.6% < 95%', pass: false },
    { id: 'p1', l: 'No open P1 alerts', s: p1.length ? 'fail' : 'pass', d: p1.length ? p1.length + ' open: ' + p1.map((a) => a.title).join('; ') : 'none open', fix: p1.length > 0, pass: false },
    { id: 'dd', l: 'Drawdown above the kill line', s: 'pass', d: '−11.2% from peak · kill line −25%', pass: false },
    { id: 'broker', l: 'Broker reachable', s: sc.env === 'ghost' || sc.health !== 'error' ? 'pass' : 'fail', d: sc.env === 'ghost' ? 'Ghost — rehearsal, no broker needed' : sc.health === 'error' ? 'gateway unreachable' : 'reachable', pass: false },
    { id: 'ack', l: 'Acknowledge the deviations that will apply', s: 'man', d: ['excluded: ' + (sc.controls.excludedSymbols.length + 23) + ' names', ...(sc.controls.lockedSymbols.length ? ['locked: ' + sc.controls.lockedSymbols.join(', ')] : [])].join(' · '), pass: false },
  ];
  for (const x of checks) x.pass = x.s === 'pass' || (x.s === 'man' && !!ticks[x.id] && (!x.note || note.trim().length >= 8));
  return { checks, ok: checks.every((x) => x.pass), n: checks.filter((x) => x.pass).length };
}

export function audit(log: AuditRow[]): AuditPayload {
  const rows: AuditRow[] = [...log, ...sample.audit.map((r) => ({ ...r, at: r.t }))];
  return { rows, logins: [{ at: '2026-09-25T22:01:13Z', user: 'owner', event: 'login', detail: 'ok' }, { at: '2026-09-25T21:58:40Z', user: 'owner', event: 'login_failed', detail: 'bad code' }] };
}

export function performance(sc: Sc): PerformancePayload {
  const acct = sc.env !== 'ghost';
  const eq = sample.equityCurve;
  const last = eq[eq.length - 1];
  const r = (a: number, b: number) => a / b - 1;
  const ret = (k: 'model' | 'account' | 'benchmark') => r(last[k], eq[0][k]);
  const book = S.holdings(sc).positions;
  const trips = S.roundTrips(sc).trips;
  const bySector = new Map<string, number>();
  for (const h of book) bySector.set(h.sector, (bySector.get(h.sector) ?? 0) + (h.last - h.avgCost) * h.shares);
  const fills = acct ? S.history(sc).orders.slice(0, 24).map((o, i) => ({ date: o.fillDate, symbol: o.symbol, side: o.side === 'BUY' ? 'buy' : 'sell', bps: [2.1, -1.4, 4.8, 0.6, 13.2, -3.1, 1.9, 6.4][i % 8] })) : [];
  return {
    since: sample.twinStart, sessions: eq.length,
    metrics: [
      { key: 'total', label: 'Total return', note: 'since Tue 18 Aug', unit: 'pct', model: ret('model'), account: acct ? ret('account') : null, bench: ret('benchmark'), ref: 2.98 },
      { key: 'cagr', label: 'CAGR', note: 'needs ≥ 63 sessions', unit: 'pct', model: null, account: null, bench: null, ref: 0.368 },
      { key: 'sharpe', label: 'Sharpe', note: 'annualised, daily, rf = 0', unit: 'ratio', model: -2.41, account: acct ? -2.44 : null, bench: 1.62, ref: 1.22 },
      { key: 'sortino', label: 'Sortino', note: 'downside deviation', unit: 'ratio', model: -3.05, account: acct ? -3.1 : null, bench: 2.4, ref: 1.81 },
      { key: 'mdd', label: 'Max drawdown', note: 'peak to trough', unit: 'pct', model: -0.112, account: acct ? -0.113 : null, bench: -0.041, ref: -0.162 },
      { key: 'calmar', label: 'Calmar', note: 'CAGR ÷ max drawdown', unit: 'ratio', model: null, account: null, bench: null, ref: 2.27 },
      { key: 'vol', label: 'Volatility', note: 'annualised', unit: 'pct', model: 0.31, account: acct ? 0.31 : null, bench: 0.18, ref: 0.27 },
      { key: 'win', label: 'Win rate', note: 'closed round trips', unit: 'pct', model: trips.length ? trips.filter((t) => t.pnl > 0).length / trips.length : null, account: null, bench: null, ref: 0.47 },
      { key: 'trades', label: 'Trades', note: 'orders filled', unit: 'count', model: 44, account: null, bench: null, ref: 1210 },
    ],
    monthly: [
      { label: 'Twin 2026', live: true, months: [null, null, null, null, null, null, null, 0.0002, -0.0957, null, null, null], year: -0.0955 },
      { label: 'OOS 2026', live: false, months: [0.041, -0.022, 0.067, 0.012, 0.085, -0.031, 0.044, 0.009, null, null, null, null], year: 0.218 },
      { label: 'OOS 2025', live: false, months: [0.031, 0.052, -0.064, -0.018, 0.071, 0.048, 0.022, -0.011, 0.039, 0.057, -0.026, 0.033], year: 0.276 },
      { label: 'OOS 2024', live: false, months: [0.012, 0.081, 0.054, -0.047, 0.036, 0.062, -0.029, 0.018, 0.024, -0.015, 0.091, -0.008], year: 0.317 },
      { label: 'OOS 2023', live: false, months: [0.058, 0.007, 0.033, 0.021, 0.094, 0.061, 0.038, -0.043, -0.052, -0.036, 0.105, 0.072], year: 0.459 },
    ],
    periods: { today: { pnl: 642.14, pct: 0.0072 }, wtd: { pnl: -1832.86, pct: -0.0199 }, mtd: { pnl: -9572.86, pct: -0.0957 }, all: { pnl: last.model - eq[0].model, pct: ret('model') } },
    byHolding: [...book.map((h) => ({ label: h.symbol, value: (h.last - h.avgCost) * h.shares })).sort((a, b) => b.value - a.value), { label: 'Closed (' + trips.length + ')', value: trips.reduce((a, t) => a + t.pnl, 0) }, { label: 'Fees', value: -28.56 }],
    bySector: [...bySector].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value),
    gap: acct ? [{ label: 'Slippage', value: -31.2 }, { label: 'Drift and other', value: -12.49 }, { label: 'Account − Model', value: -43.69 }] : null,
    execution: acct ? { fills, avgBps: 3.1, outliers: fills.filter((f) => Math.abs(f.bps) > 10).length, missed: 0, trackingError: [{ month: '2026-08', value: 0.0011 }, { month: '2026-09', value: 0.0019 }] } : null,
    dividends: { gross: 0, withholding: 0 },
    reference: { sharpe: 1.22, mdd: -0.162, cagr: 0.368, total: 2.98, calmar: 2.27, trades: 1210, window: ['2023-01-03', '2026-08-04'] },
  };
}

export function agent(sc: Sc): AgentPayload {
  return {
    handle: 'trend', freezeCommit: 'a41f0c2e',
    params: sample.params.map((p) => ({ k: p.k, v: p.v, lo: p.lo, hi: p.hi, frozen: p.fz })),
    regime: { score: 0.71, ixic_vs_sma200: 0.062, ixic_vs_sma50: 0.011, breadth: 0.54, mood: 'trending' },
    mood: 'trending',
    sentiment: sample.sentiment.map((s) => ({ date: s.date, s: s.sentiment })),
    journal: sample.journal.map((j) => ({ date: S.labelIso(j.dw), mood: j.m, sentiment: j.s, note: j.t })),
    adaptations: [],
    oosAdaptations: [
      { date: '2026-05-01', changes: { EXP_MAX: 0.95, TRAIL_ATR: 5.0 }, note: 'Trend persistence improved; trailing stops widened' },
      { date: '2026-01-29', changes: { RISK_PER_TRADE: 0.016 }, note: 'Volatility fell; risk per trade raised' },
    ],
    nextAdapt: sc.controls.pauseAdapt ? null : '2026-11-16', adaptEvery: 63, sessions: 28,
    adaptPaused: sc.controls.pauseAdapt, adaptPausedSince: sc.controls.pauseAdapt ? '2026-09-25' : null,
    calibration: { window: ['2023-01-03', '2026-08-04'], horizon_sessions: 20, position_days: 9981, round_trips: 403, method: 'every held position-day scored', bands: [
      { band: 'high', n: 9353, hit_rate: 0.4974, avg_return: 0.0307, trade_won_rate: 0.6791 },
      { band: 'med', n: 622, hit_rate: 0.455, avg_return: 0.0369, trade_won_rate: 0.2299 },
      { band: 'low', n: 6, hit_rate: 0.6667, avg_return: -0.0002, trade_won_rate: 0 },
    ] },
    liveBands: [{ band: 'high', n: 11, hit: 0.45, ret: 0.012 }, { band: 'med', n: 6, hit: 0.33, ret: -0.031 }, { band: 'low', n: 0, hit: null, ret: null }],
  };
}
