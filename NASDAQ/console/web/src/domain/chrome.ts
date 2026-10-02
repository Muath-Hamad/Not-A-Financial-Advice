// Global chrome: top bar, banners, nav badges, freshness labels and the
// empty-state copy. Ported from vmTop, vmBanners, vmNav, vmFresh, vmEmpty.

import type { Alert, Intent as OrderIntent, Position } from '@/api/types';
import { control, nav, toast, type Intent, type Screen } from './actions';
import { openAlerts, pendingRows, pill, tonight, type TimelineStep } from './core';
import type { Ctx } from './ctx';
import { ago, daysBetween, hm, wdLabel } from '@/lib/dates';

export interface TopBar {
  envL: string;
  envCls: string;
  envT: string;
  pillCls: string;
  pillL: string;
  pillS: string;
  tl: TimelineStep[];
  sync1: string;
  sync2: string;
  syncCls: string;
  syncT: string;
  p1: string;
  p2: string;
  p1Cls: string;
  p2Cls: string;
  bellT: string;
  cd: string;
}

export function selectTop(c: Ctx, alerts: Alert[]): TopBar {
  const env = c.env;
  const p = pill(c);
  const al = openAlerts(alerts);
  const p1 = al.filter((a) => a.priority === 'P1').length;
  const p2 = al.filter((a) => a.priority === 'P2').length;
  const fa = c.facts;
  let sync1 = 'Ledger synced ' + ago(fa.ledger.syncedMinAgo) + ' ago';
  let sync2 = env === 'ghost' ? 'No broker (ghost)' : 'Broker live';
  let syncCls = '';
  if (c.data === 'error') {
    if (fa.ledger.down) { sync1 = 'Indexer down ' + ago(fa.ledger.downMin); sync2 = 'last commit ' + (fa.ledger.commit ?? '—'); } else sync2 = 'Broker unreachable';
    syncCls = 'red';
  }
  if (c.data === 'loading') { sync1 = 'Syncing ledger…'; syncCls = 'amber'; }
  if (c.data === 'stale') { sync2 = 'model book ' + daysBetween(fa.model.asof, fa.today) + ' days old'; syncCls = 'amber'; }
  const next = c.released || fa.submitInMin == null ? 'Open in ' + hm(fa.openInMin) : 'Submit in ' + hm(fa.submitInMin);
  const cdMap = { running: next, paused: next, held: 'Release by 09:28', halted: 'Clear the halt', stopped: 'Kill active' };
  return {
    envL: { ghost: 'GHOST', paper: 'PAPER', live: 'LIVE' }[env],
    envCls: env,
    envT: { ghost: 'Ghost — no broker; nightly rehearsal against the twin', paper: 'Paper — Alpaca paper account', live: 'LIVE — real money (Alpaca live, cash account)' }[env],
    pillCls: p.cls, pillL: p.l, pillS: p.s,
    tl: tonight(c),
    sync1, sync2, syncCls,
    syncT: 'Read model indexed from the ledger repository',
    p1: String(p1), p2: String(p2),
    p1Cls: p1 ? 'p1' : 'zero', p2Cls: p2 ? 'p2' : 'zero',
    bellT: 'Alerts — ' + p1 + ' open P1, ' + p2 + ' open P2',
    cd: c.data === 'stale' ? 'Cycle A failing' : cdMap[c.trading],
  };
}

export interface BannerAct {
  l: string;
  intent: Intent;
  cls: string;
}

export interface Banner {
  tone: 'red' | 'amber' | 'blue';
  title: string;
  text: string;
  acts: BannerAct[];
}

export function selectBanners(c: Ctx): Banner[] {
  const B: Banner[] = [];
  const own = c.role === 'owner';
  const g = c.env === 'ghost';
  const A = (l: string, intent: Intent, cls = ''): BannerAct => ({ l, intent, cls });
  const fa = c.facts;
  const fl = fa.failing;
  if (c.data === 'stale' && fl) {
    const title = fl.count === 1 ? 'Cycle A failed on ' + wdLabel(fl.to) + '.' : 'Cycle A has failed ' + fl.count + ' sessions in a row (' + wdLabel(fl.from) + ' → ' + wdLabel(fl.to) + ').';
    B.push({ tone: 'red', title, text: fl.reason + '. Model book is from ' + wdLabel(fa.model.asof) + '.', acts: [A('View details', nav('health')), ...(own ? [A('Re-run Cycle A', control('rerun', 'Cycle A'), 'primary')] : [])] });
  }
  if (c.data === 'error') B.push(g
    ? { tone: 'red', title: 'Indexer unreachable.', text: 'The ledger has not synced for ' + ago(fa.ledger.downMin) + '; panels show the last indexed commit ' + (fa.ledger.commit ?? '—') + '.', acts: [A('View health', nav('health')), A('Retry', toast('Retrying… the indexer is still unreachable'))] }
    : { tone: 'red', title: 'Broker unreachable.', text: 'Gateway timeout after 10 s (last success ' + (fa.broker?.lastOk ?? '—') + '). Account figures are last known; immediate broker commands will fail.', acts: [A('View health', nav('health')), A('Retry', toast('Retrying… the gateway is still timing out'))] });
  if (c.trading === 'halted') {
    const h = fa.halt;
    B.push({ tone: 'red', title: 'Submit halted — reconciliation break.', text: (h ? 'Cycle B 09:50: ' + h.symbol + ' expected ' + h.expected + ', the account holds ' + h.actual + '. ' : '') + 'Nothing is sent until you clear the halt with a cause.', acts: own ? [A('Resolve in Controls', nav('controls'), 'primary')] : [] });
  }
  if (c.trading === 'stopped') B.push({ tone: 'red', title: 'Trading stopped (kill switch).', text: c.flatten ? 'Every position sells at Monday’s open. The twin keeps running for comparison.' : 'No orders are ledgered or sent. The twin keeps running for comparison.', acts: own ? [A('Resume…', { kind: 'preflight' })] : [] });
  if (c.trading === 'held') B.push({ tone: 'blue', title: 'Approval mode:', text: 'tonight’s orders need your release before 09:28 ET.', acts: own ? [A('Review & release', nav('controls'), 'primary')] : [] });
  if (c.trading === 'paused') B.push({ tone: 'amber', title: 'Entries paused.', text: 'Buys are blocked by pause_entries; sells, stops and forced exits still flow.', acts: own ? [A('Controls', nav('controls'))] : [] });
  return B;
}

export interface NavBadges {
  bHold: string;
  bOrd: string;
  bComp: string;
  bCompCls: string;
  bCtl: string;
  bCtlCls: string;
  bHealth: string;
  bHealthCls: string;
  bAl: string;
  bAlCls: string;
  ctlAlert: boolean;
  moreAlert: boolean;
  moreN: string;
}

export const MORE_SCREENS: Screen[] = ['performance', 'compliance', 'agent', 'health', 'alerts', 'audit', 'roadmap', 'glossary', 'settings', 'more'];

export function selectNav(c: Ctx, positions: Position[], intents: OrderIntent[], alerts: Alert[]): NavBadges {
  const pend = pendingRows(intents, positions, c).filter((x) => x.live).length;
  const al = openAlerts(alerts);
  const p1 = al.filter((a) => a.priority === 'P1').length;
  const rev = positions.filter((h) => h.review && !c.controls.forcedExits.includes(h.symbol)).length;
  const ctlAlert = ['held', 'halted', 'stopped'].includes(c.trading);
  return {
    bHold: c.data === 'loading' ? '' : c.data === 'empty' ? '0' : String(positions.length),
    bOrd: pend ? String(pend) : '',
    bComp: rev ? String(rev) : '',
    bCompCls: rev ? 'amber' : '',
    bCtl: ctlAlert ? '!' : '',
    bCtlCls: ctlAlert ? (c.trading === 'held' ? 'amber' : 'red') : '',
    bHealth: c.data === 'stale' ? String(c.facts.failing?.count ?? '!') : c.data === 'error' ? '!' : '',
    bHealthCls: c.data === 'stale' || c.data === 'error' ? 'red' : '',
    bAl: al.length ? String(al.length) : '',
    bAlCls: p1 ? 'red' : al.length ? 'amber' : '',
    ctlAlert,
    moreAlert: p1 > 0,
    moreN: String(p1),
  };
}

export interface FreshLabel {
  cls: '' | 'amber' | 'red';
  l: string;
  s: string;
}

export interface Freshness {
  model: FreshLabel;
  acct: FreshLabel;
  ledger: FreshLabel;
  broker: FreshLabel;
}

/** Data age per panel (docs/08 §11): amber > 1 session behind, red > 2. */
export function selectFresh(c: Ctx): Freshness {
  const g = c.env === 'ghost';
  const fa = c.facts;
  const m = fa.model;
  const age = ago(m.ageMin);
  const behind = m.sessionsBehind;
  const days = daysBetween(m.asof, fa.today);
  const fr: Freshness = {
    model: { cls: behind > 2 ? 'red' : behind > 1 ? 'amber' : '', l: 'Model book · ' + wdLabel(m.asof) + (m.builtAt ? ' ' + m.builtAt : '') + ' · ' + age, s: age },
    acct: { cls: '', l: g ? 'No broker (ghost)' : 'Account · ' + (fa.accountAt ?? '—'), s: fa.accountAt ?? '—' },
    ledger: { cls: '', l: ago(fa.ledger.syncedMinAgo) + ' ago', s: ago(fa.ledger.syncedMinAgo) },
    broker: { cls: '', l: g ? 'Ghost · no broker' : 'Live · ' + (fa.broker?.latencyMs ?? '—') + ' ms', s: '' },
  };
  if (c.data === 'stale') fr.model = { cls: 'red', l: 'Stale · model book from ' + wdLabel(m.asof) + ' (' + days + ' days)', s: 'Stale · ' + days + ' d' };
  if (c.data === 'error') {
    if (fa.ledger.down) {
      fr.ledger = { cls: 'red', l: 'Indexer down · ' + ago(fa.ledger.downMin), s: ago(fa.ledger.downMin) };
      fr.model = { cls: 'amber', l: 'Last indexed ' + ago(fa.ledger.downMin) + ' ago', s: ago(fa.ledger.downMin) };
    } else {
      fr.acct = { cls: 'red', l: 'Broker unreachable · last ' + (fa.broker?.lastOk ?? '—'), s: 'Error' };
      fr.broker = { cls: 'red', l: 'Unreachable · timeout 10 s', s: '' };
    }
  }
  return fr;
}

export interface EmptyCopy {
  title: string;
  h: string;
  p: string;
}

function emptyCopy(start: string): Partial<Record<Screen, [string, string, string]>> {
  const d = wdLabel(start);
  return {
    overview: ['Overview', 'Nothing to show yet', 'The account starts in cash on ' + d + '. The first Cycle A runs at 17:05 ET that evening, and positions appear after the next 09:30 ET open.'],
    holdings: ['Holdings', 'No positions yet', 'The account starts in cash on ' + d + '. Holdings appear after the first fills at the 09:30 ET open the next morning.'],
    orders: ['Orders', 'No orders yet', 'The first orders are ledgered by Cycle A on ' + d + ' at 17:05 ET and sent by the 19:15 ET submit. In approval mode you release each night by hand.'],
    performance: ['Performance', 'No history yet', 'Performance starts with the first session on ' + d + '. The OOS reference — Sharpe 1.22, max drawdown −16.2%, CAGR 36.8% — will sit next to it.'],
    compliance: ['Compliance', 'No holdings to screen', 'The universe is screened and frozen. Per-holding compliance cards appear once positions exist.'],
  };
}

export function selectEmpty(screen: Screen, start = '2026-11-02'): EmptyCopy {
  const m = emptyCopy(start)[screen] || ['', '', ''];
  return { title: m[0], h: m[1], p: m[2] };
}

/** Screens that still render in the Empty state (system screens). */
export const SYSTEM_SCREENS: Screen[] = ['controls', 'agent', 'health', 'alerts', 'audit', 'roadmap', 'glossary', 'settings', 'more'];
