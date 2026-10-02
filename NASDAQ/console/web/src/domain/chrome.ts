// Global chrome: top bar, banners, nav badges, freshness labels and the
// empty-state copy. Ported from vmTop, vmBanners, vmNav, vmFresh, vmEmpty.

import type { Alert, Intent as OrderIntent, Position } from '@/api/types';
import { control, nav, toast, type Intent, type Screen } from './actions';
import { openAlerts, pendingRows, pill, tonight, type TimelineStep } from './core';
import type { Ctx } from './ctx';

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
  let sync1 = 'Ledger synced 2 min ago';
  let sync2 = env === 'ghost' ? 'No broker (ghost)' : 'Broker live';
  let syncCls = '';
  if (c.data === 'error') {
    if (env === 'ghost') { sync1 = 'Indexer down 14 min'; sync2 = 'last commit 7f3c2a1'; } else sync2 = 'Broker unreachable';
    syncCls = 'red';
  }
  if (c.data === 'loading') { sync1 = 'Syncing ledger…'; syncCls = 'amber'; }
  if (c.data === 'stale') { sync2 = 'model book 6 days old'; syncCls = 'amber'; }
  const cdMap = { running: c.released ? 'Open in 13h59m' : 'Submit in 1h12m', paused: 'Submit in 1h12m', held: 'Release by 09:28', halted: 'Clear the halt', stopped: 'Kill active' };
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
  if (c.data === 'stale') B.push({ tone: 'red', title: 'Cycle A has failed 4 sessions in a row (Mon 28 Sep → Thu 1 Oct).', text: 'Data gate tripped: coverage at asof 0.6% < 95%. Model book is from Fri 25 Sep.', acts: [A('View details', nav('health')), ...(own ? [A('Re-run Cycle A', control('rerun', 'Cycle A'), 'primary')] : [])] });
  if (c.data === 'error') B.push(g
    ? { tone: 'red', title: 'Indexer unreachable.', text: 'The ledger has not synced for 14 min; panels show the last indexed commit 7f3c2a1.', acts: [A('View health', nav('health')), A('Retry', toast('Retrying… the indexer is still unreachable'))] }
    : { tone: 'red', title: 'Broker unreachable.', text: 'Gateway timeout after 10 s (last success 17:41 ET). Account figures are last known; immediate broker commands will fail.', acts: [A('View health', nav('health')), A('Retry', toast('Retrying… the gateway is still timing out'))] });
  if (c.trading === 'halted') B.push({ tone: 'red', title: 'Submit halted — reconciliation break.', text: 'Cycle B 09:50: ROKU expected 75, the account holds 74. Nothing is sent until you clear the halt with a cause.', acts: own ? [A('Resolve in Controls', nav('controls'), 'primary')] : [] });
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

export const MORE_SCREENS: Screen[] = ['performance', 'compliance', 'agent', 'health', 'alerts', 'audit', 'roadmap', 'settings', 'more'];

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
    bHealth: c.data === 'stale' ? '4' : c.data === 'error' ? '!' : '',
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
  const fr: Freshness = {
    model: { cls: '', l: 'Model book · Fri 25 Sep 17:05 ET · 58 min', s: '58 min' },
    acct: { cls: '', l: g ? 'No broker (ghost)' : 'Account · 2 min ago', s: '2 min' },
    ledger: { cls: '', l: '2 min ago', s: '2 min' },
    broker: { cls: '', l: g ? 'Ghost · no broker' : 'Live · 142 ms', s: '' },
  };
  if (c.data === 'stale') fr.model = { cls: 'red', l: 'Stale · model book from Fri 25 Sep (6 days)', s: 'Stale · 6 d' };
  if (c.data === 'error') {
    if (g) {
      fr.ledger = { cls: 'red', l: 'Indexer down · 14 min', s: '14 min' };
      fr.model = { cls: 'amber', l: 'Last indexed 14 min ago', s: '14 min' };
    } else {
      fr.acct = { cls: 'red', l: 'Broker unreachable · last 17:41 ET', s: 'Error' };
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

const EMPTY: Partial<Record<Screen, [string, string, string]>> = {
  overview: ['Overview', 'Nothing to show yet', 'The Alpaca paper account starts in cash on Mon 2 Nov 2026. The first Cycle A runs at 17:05 ET that evening, and positions appear after the open on Tue 3 Nov.'],
  holdings: ['Holdings', 'No positions yet', 'Account starts in cash on Mon 2 Nov. Holdings appear after the first fills at the 09:30 ET open the next morning.'],
  orders: ['Orders', 'No orders yet', 'The first orders are ledgered by Cycle A on Mon 2 Nov at 17:05 ET and sent by the 19:15 ET submit. In approval mode you release each night by hand.'],
  performance: ['Performance', 'No history yet', 'Performance starts with the first paper session on Mon 2 Nov. The OOS reference — Sharpe 1.22, max drawdown −16.2%, CAGR 36.8% — will sit next to it.'],
  compliance: ['Compliance', 'No holdings to screen', 'The 319-name universe is screened and frozen. Per-holding compliance cards appear once positions exist.'],
};

export function selectEmpty(screen: Screen): EmptyCopy {
  const m = EMPTY[screen] || ['', '', ''];
  return { title: m[0], h: m[1], p: m[2] };
}

/** Screens that still render in the Empty state (system screens). */
export const SYSTEM_SCREENS: Screen[] = ['controls', 'agent', 'health', 'alerts', 'audit', 'roadmap', 'settings', 'more'];
