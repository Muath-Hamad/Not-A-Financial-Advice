// Controls screen (M1): the executive desk. Ported from the prototype's
// vmControls; the impact of each action comes from the server's preview.

import type { ControlsPayload, Position } from '@/api/types';
import { f } from '@/lib/format';
import { wdLabel } from '@/lib/dates';
import { confOf, sharia } from './core';
import type { ControlAction } from './actions';
import type { Ctx } from './ctx';

export const CATEGORIES = ['Compliance', 'Risk', 'Operational', 'Test'] as const;
export type Category = (typeof CATEGORIES)[number];

export function categoryFor(a: ControlAction): Category {
  return ({ force_exit: 'Compliance', unexclude: 'Compliance', stop: 'Risk', flatten: 'Risk', pause: 'Risk', trim: 'Risk', gross: 'Risk', lock: 'Risk' } as Partial<Record<ControlAction, Category>>)[a] ?? 'Operational';
}

export function quickReasons(a: ControlAction): string[] {
  const Q: Partial<Record<ControlAction, string[]>> = {
    stop: ['Data gate failing — stop until the feed is fixed', 'Broker anomaly: unexpected open orders', 'Market-wide halt or circuit breaker'],
    flatten: ['Exit everything: evaluation ended early', 'Account compromise suspected'],
    pause: ['FOMC tomorrow; no new risk', 'Data check after a vendor outage'],
    resume_entries: ['Data verified against the NASDAQ source'],
    resume: ['Root cause fixed; preflight checklist green'],
    force_exit: ['Sharia ruling: exclude (D1)', 'Business activity changed after the re-screen'],
    lock: ['Hold through the earnings review; no agent trades', 'Pending Sharia ruling — freeze the position'],
    unlock: ['Review finished; hand back to the agent'],
    trim: ['Reduce concentration ahead of earnings', 'Risk: position is near its stop'],
    release: ['Reviewed tonight’s orders — all as expected'],
    clear_halt: ['Corporate action: the broker delivered shares late; verified in account activities'],
    adapt: ['Freeze parameters during the evaluation review'],
    gross: ['Reduce gross exposure into month-end'],
    rerun: ['Data feed recovered; re-run the step'],
    unexclude: ['Re-screen reversal confirmed'],
    cancel_manual: ['Changed my mind; let the agent manage it'],
  };
  return Q[a] ?? ['Operational change'];
}

export interface OverrideRow {
  s: string;
  n: string;
  w: string;
  c: string;
  band: string;
  bandL: string;
  g: string;
  gCls: string;
  stat: string;
  locked: boolean;
  forced: boolean;
  status: string;
  stCls: string;
}

export function selectControls(c: Ctx, p: ControlsPayload, positions: Position[]) {
  const T = c.trading;
  const ctl = p.controls;
  const fa = c.facts;
  const nextA = 'next Cycle A';
  const b1 = T === 'paused'
    ? { l: 'Resume entries', cls: '', action: 'resume_entries' as ControlAction, eff: 'the next 19:15 ET submit', sub: 'Buys allowed again', dis: false }
    : { l: 'Pause entries', cls: 'warn-o', action: 'pause' as ControlAction, eff: 'the next 19:15 ET submit', sub: 'Blocks buys · sells and stops still flow', dis: T === 'stopped' };
  const b2 = T === 'stopped'
    ? { l: 'Resume trading…', cls: 'primary', action: 'resume' as ControlAction, eff: nextA, sub: 'Preflight checklist first', dis: false }
    : { l: 'STOP TRADING', cls: 'danger', action: 'stop' as ControlAction, eff: 'immediate', sub: 'Kill switch · cancels open orders now', dis: false };
  const b3 = { l: 'Stop & flatten…', cls: 'danger-o', action: 'flatten' as ControlAction, eff: 'kill now · sells at the next open', sub: 'Sells every position at the next open', dis: c.flatten };
  const big = { running: 'RUNNING', paused: 'ENTRIES PAUSED', held: 'NIGHT HELD', halted: 'HALTED', stopped: 'STOPPED' }[T];
  const since = {
    running: 'Running · every cycle reads controls.json',
    paused: 'Entries paused — buys are blocked',
    held: 'Held — approval mode; the night waits for your release',
    halted: 'Halted since ' + (p.halt?.since ? wdLabel(p.halt.since) : '—') + ' — reconciliation break',
    stopped: 'Stopped' + (c.stopAt ? ' since ' + c.stopAt : '') + ' — kill switch',
  }[T];
  const reads = {
    running: 'The next 19:15 ET submit re-checks controls.json before sending',
    paused: 'The submit skips buys; the next Cycle A ledgers no entries',
    held: 'Waiting for your release — the window closes at 09:28 ET',
    halted: 'The submit sends nothing until the halt is cleared with a cause',
    stopped: 'Every cycle is frozen; the twin keeps running for comparison',
  }[T];
  const ovr: OverrideRow[] = positions.map((h) => {
    const cv = confOf(h, c);
    const sv = sharia(h, c);
    const locked = ctl.locked_symbols.includes(h.symbol);
    const forced = ctl.excluded_symbols.includes(h.symbol);
    const trim = ctl.manual_orders.find((m) => m.symbol === h.symbol);
    let status = 'Agent-managed';
    let stCls = 'muted';
    if (locked) { status = 'Locked — agent skips'; stCls = 'warn'; }
    if (trim) { status = 'Trim ' + (trim.qty ?? '') + ' sh queued'; stCls = 'info'; }
    if (forced) { status = 'Exit queued (forced)'; stCls = 'danger'; }
    return {
      s: h.symbol, n: h.name, w: f(((h.shares * h.last) / c.equity) * 100, 1) + '%',
      c: cv ? String(cv.tot) : '—', band: cv ? cv.band : 'none', bandL: cv ? cv.bandL : 'Pending',
      g: sv.g, gCls: sv.gCls, stat: sv.short, locked, forced, status, stCls,
    };
  });
  return {
    b1, b2, b3, big, since, reads,
    pending: p.pending,
    held: p.heldNight || T === 'held',
    halted: T === 'halted' || !!p.halt?.halted,
    haltDiffs: p.halt?.diffs ?? [],
    haltSince: p.halt?.since ?? null,
    ovr,
    excluded: ctl.excluded_symbols,
    locked: ctl.locked_symbols,
    manual: ctl.manual_orders,
    grossCap: ctl.gross_cap == null ? null : Math.round(ctl.gross_cap * 100),
    exposure: p.exposure,
    drawdown: p.drawdown,
    limits: p.limits,
    adaptPaused: ctl.pause_adapt,
    adaptSince: ctl.pause_adapt_since,
    write: p.write,
    dispatch: p.dispatch,
    gateway: p.gateway,
    stale: c.data === 'stale',
    err: c.data === 'error' && c.env !== 'ghost',
    nextOpen: wdLabel(fa.nextOpen),
  };
}
