import { describe, expect, it } from 'vitest';
import { defaultScenario, snapshot, type Scenario } from '@/mocks/scenario';
import { ctxFrom } from './ctx';
import { confOf, exitOf, gradeOf, pendingRows, pill, sharia, sortAlerts, tonight } from './core';
import { selectBanners, selectFresh, selectNav, selectTop } from './chrome';
import { attention, selectCompStrip, selectEquity, selectOverview } from './overview';
import { filterRows, NO_FILTERS, selectDrawer, selectHoldings, selectSide } from './holdings';
import { selectHistory, selectPending, selectRoundTrips, slippageBps } from './orders';
import { selectCards, selectUniverse } from './compliance';
import { selectHealth } from './health';
import { selectRoadmap } from './roadmap';

function setup(patch: Partial<Scenario> = {}) {
  const sc = { ...defaultScenario(), ...patch };
  const s = snapshot(sc);
  const c = ctxFrom(s.overview);
  const pos = s.holdings.positions;
  const pos1 = (sym: string) => pos.find((h) => h.symbol === sym)!;
  return { sc, s, c, pos, pos1 };
}

describe('not-yet-available data', () => {
  it('says pending instead of inventing confidence and stops', () => {
    const { c, s, pos } = setup();
    const bare = pos.map((h) => ({ ...h, confidence: null, initialStop: null, trailingStop: null, atr: null, rank: null, dayPct: null }));
    expect(confOf(bare[0], c)).toBeNull();
    expect(exitOf(bare[0])).toMatchObject({ p: '—', d: 'awaiting insights (M3)' });
    const v = selectHoldings(c, bare, s.pending.intents, 'model', NO_FILTERS, { realized: true, held: true, pending: true }, { cls: '', l: '' });
    expect(v.rows[0]).toMatchObject({ c: '—', band: 'none', day: '' });
    expect(v.tC).toBe('—');
  });

  it('grades by headroom: B within 10 pp of a limit, C within 3 pp', () => {
    expect(gradeOf(5, 5, false, false)).toBe('A');
    expect(gradeOf(22, 5, false, false)).toBe('B');
    expect(gradeOf(28, 5, false, false)).toBe('C');
    expect(gradeOf(null, 5, false, false)).toBe('C');
    expect(gradeOf(5, 5, true, false)).toBe('C');
    expect(gradeOf(5, 5, false, true)).toBe('F');
  });
});

describe('confidence (docs/08 §6)', () => {
  it('weights Signal 40 · Risk room 30 · Regime 20 · Data 10 and bands at 70/40', () => {
    const { c, pos1 } = setup();
    expect(confOf(pos1('TXG'), c)).toMatchObject({ tot: 82, band: 'high', bandL: 'High' });
    expect(confOf(pos1('ORKA'), c)).toMatchObject({ tot: 37, band: 'low', bandL: 'Low' });
    expect(confOf(pos1('ROKU'), c)!.tot).toBe(61);
  });

  it('marks the Data sub-score stale when Cycle A is failing', () => {
    const { c, pos1 } = setup({ health: 'stale' });
    expect(confOf(pos1('TXG'), c)!.c[3]).toBe(15);
    expect(confOf(pos1('TXG'), c)!.title).toContain('model conviction, not a forecast');
  });
});

describe('Sharia grade (docs/08 §5)', () => {
  it('grades a clean name A, a review-flagged name C and a forced exit F', () => {
    const { c, pos1 } = setup();
    expect(sharia(pos1('HALO'), c)).toMatchObject({ g: 'A', short: 'Compliant' });
    expect(sharia(pos1('ROKU'), c)).toMatchObject({ g: 'C', status: 'Under review', ruling: 'Due Fri 30 Oct 2026 (D1)' });
    const forced = setup({ controls: { ...defaultScenario().controls, forcedExits: ['ROKU'] } });
    expect(sharia(forced.pos1('ROKU'), forced.c)).toMatchObject({ g: 'F', status: 'Excluded — exit queued' });
  });

  it('shows headroom against the 30% line', () => {
    const { c, pos1 } = setup();
    expect(sharia(pos1('HALO'), c).debt).toMatchObject({ v: '18.6%', head: '11.4 pp headroom', cls: 'ok' });
  });

  it('never invents a purification number', () => {
    const { c, pos1 } = setup();
    expect(sharia(pos1('MU'), c).purif).toBe('Next dividend ~$0.69 gross (6 × $0.115, pay Tue 20 Oct) · rate pending');
    expect(sharia(pos1('TXG'), c).purif).toBe('No dividend received · nothing due');
  });
});

describe('nearest exit', () => {
  it('picks the higher of the initial and trailing stop, in ATRs', () => {
    const { pos1 } = setup();
    expect(exitOf(pos1('ORKA'))).toMatchObject({ k: 'Initial stop', p: '$82.33', d: '0.4 ATR away', cls: 'warn', near: true });
    expect(exitOf(pos1('MU'))).toMatchObject({ k: 'Trailing stop', p: '$874.00' });
    expect(exitOf(pos1('KNSA'))).toMatchObject({ k: 'Rank exit', p: 'rank 44 > 30' });
  });
});

describe('pending orders', () => {
  it('blocks CELC on the ADV cap and sends the other three', () => {
    const { s, c, pos } = setup();
    const rows = pendingRows(s.pending.intents, pos, c);
    expect(rows.map((r) => [r.symbol, r.live, r.state])).toEqual([
      ['CRDO', true, 'Ledgered · awaiting 19:15 submit'],
      ['ALAB', true, 'Ledgered · awaiting 19:15 submit'],
      ['KNSA', true, 'Ledgered · awaiting 19:15 submit'],
      ['CELC', false, 'Blocked'],
    ]);
  });

  it('blocks buys when entries are paused but lets the sell through', () => {
    const { s, c, pos } = setup({ trading: 'paused' });
    const rows = pendingRows(s.pending.intents, pos, c);
    expect(rows.find((r) => r.symbol === 'CRDO')).toMatchObject({ guardrail: 'pause_entries', live: false });
    expect(rows.find((r) => r.symbol === 'KNSA')).toMatchObject({ live: true });
  });

  it('cancels everything on the kill switch', () => {
    const { s, c, pos } = setup({ trading: 'stopped' });
    const rows = pendingRows(s.pending.intents, pos, c);
    expect(rows.filter((r) => r.live)).toHaveLength(0);
    expect(rows[0].state).toBe('Canceled · kill');
  });

  it('adds forced exits and manual trims from controls', () => {
    const controls = { ...defaultScenario().controls, forcedExits: ['ROKU'], manualOrders: [{ symbol: 'TXG', shares: 68, pct: 50 }] };
    const { s, c, pos } = setup({ controls });
    const rows = pendingRows(s.pending.intents, pos, c);
    expect(rows.find((r) => r.id === 'f-ROKU')).toMatchObject({ side: 'SELL', qtyLabel: '75 sh (all)', source: 'forced', clientOrderId: 'console-20260925-ROKU-X1' });
    expect(rows.find((r) => r.id === 'm-TXG')).toMatchObject({ qtyLabel: '68 sh (50%)', source: 'manual' });
  });

  it('has no plan when Cycle A is failing', () => {
    const { s, c } = setup({ health: 'stale' });
    const v = selectPending(c, s.pending, s.holdings.positions);
    expect(v.none).toBe(true);
    expect(v.status).toBe('No plan · Cycle A failing');
    expect(v.nextOpen).toBe('Fri 2 Oct 09:30 ET');
  });

  it('totals the night', () => {
    const { s, c, pos } = setup();
    const v = selectPending(c, s.pending, pos);
    expect(v).toMatchObject({ buys: '$6,334.80', sells: '$2,928.12', net: '$3,406.68', hint: '4 intents · 3 to send · 1 blocked or canceled' });
  });
});

describe('chrome', () => {
  it('maps trading states to the pill', () => {
    const { c } = setup({ trading: 'held' });
    expect(pill(c)).toEqual({ cls: 'amber pulse', l: 'Night held · approval needed', s: 'Held' });
  });

  it('fails Cycle A in the timeline when stale', () => {
    const { c } = setup({ health: 'stale' });
    expect(tonight(c)[0]).toMatchObject({ cls: 'fail', g: '✗' });
  });

  it('counts open alerts by priority', () => {
    const { s, c } = setup({ env: 'ghost', health: 'stale' });
    const top = selectTop(c, s.alerts.alerts);
    expect(top).toMatchObject({ envL: 'GHOST', p1: '1', p2: '2', cd: 'Cycle A failing', sync2: 'model book 6 days old' });
  });

  it('raises the stale banner with a re-run for the owner only', () => {
    const owner = setup({ health: 'stale' });
    expect(selectBanners(owner.c)[0].acts.map((a) => a.l)).toEqual(['View details', 'Re-run Cycle A']);
    const viewer = setup({ health: 'stale', role: 'viewer' });
    expect(selectBanners(viewer.c)[0].acts.map((a) => a.l)).toEqual(['View details']);
  });

  it('badges the nav', () => {
    const { s, c, pos } = setup();
    expect(selectNav(c, pos, s.pending.intents, s.alerts.alerts)).toMatchObject({ bHold: '10', bOrd: '3', bComp: '1', bCtl: '' });
  });

  it('turns model freshness red when stale', () => {
    const { c } = setup({ health: 'stale' });
    expect(selectFresh(c).model).toEqual({ cls: 'red', l: 'Stale · model book from Fri 25 Sep (6 days)', s: 'Stale · 6 d' });
  });

  it('sorts open P1 alerts first', () => {
    const { s } = setup({ health: 'stale' });
    const sorted = sortAlerts(s.alerts.alerts);
    expect(sorted[0]).toMatchObject({ id: 'A-41', priority: 'P1', status: 'open' });
    expect(sorted[sorted.length - 1].status).toBe('resolved');
  });
});

describe('overview', () => {
  it('matches the prototype KPIs', () => {
    const { s, c, pos } = setup();
    const v = selectOverview(c, s.overview, pos, s.pending.intents, s.roadmap.decisions, s.pending.nextOpen);
    expect(v).toMatchObject({
      eq: '$90,407.14', eqSince: '−9.6%', ixic: '+3.0%', dd: '−11.2%', peak: '$101,850',
      exp: '94.8%', cash: '$4,696.00', pos: '10', posFree: '5', largest: 'GSAT 14.7%',
      ord: '3', ordSplit: '2 buys · 1 sell · 1 blocked', ordBlkL: '1 blocked · adv_cap', ordWhen: 'Mon 28 Sep 09:30 ET',
      dayWhen: 'Fri 25 Sep close', underRev: '1 under review',
    });
    expect(v.expAcct).toBe('Account 92.8% invested · cash $6,544.20');
  });

  it('lists what needs attention', () => {
    const { s, c, pos } = setup();
    const att = attention(c, pos, s.pending.intents, s.roadmap.decisions, s.pending.nextOpen);
    expect(att.map((a) => a.t)).toEqual([
      'ROKU review-flagged',
      'ORKA 0.4 ATR above its initial stop',
      'Drift 2.1% > 1.5% band',
      'KNSA rank exit at Monday’s open',
      'D8 factor2 decision due Fri 16 Oct',
    ]);
    expect(att[1].s).toBe('stop $82.33 · last $84.46 · confidence 37 Low');
    expect(att[2].s).toBe('AMD account 4 vs Model 7 — buy trimmed to cash');
    expect(att[4].s).toBe('second paper account — your call');
  });

  it('drops the account legs in Ghost', () => {
    const { s, c, pos } = setup({ env: 'ghost' });
    const v = selectOverview(c, s.overview, pos, s.pending.intents, s.roadmap.decisions, s.pending.nextOpen);
    expect(v.eqAcct).toBe('Account — starts in cash Mon 2 Nov');
    expect(v.att.some((a) => a.t.startsWith('Drift'))).toBe(false);
    expect(selectEquity(c, s.overview, 'all').account).toBeNull();
  });

  it('slices the equity range and keeps markers on their dates', () => {
    const { s, c } = setup();
    const all = selectEquity(c, s.overview, 'all');
    expect(all.dates).toHaveLength(28);
    expect(all.marks.map((m) => m.g)).toEqual(['⚑', '⚑', '■']);
    expect(selectEquity(c, s.overview, '1W').dates).toHaveLength(5);
  });

  it('splits the book by Sharia grade', () => {
    const { s, c, pos } = setup();
    const v = selectCompStrip(c, pos, s.compliance.universe);
    expect(v.stack.map((g) => g.l)).toEqual(['A', 'C', '$']);
    expect(v.rev).toBe('1 · ROKU');
    expect(v.watch).toBe('6 names');
  });
});

describe('holdings', () => {
  it('builds the model table with totals', () => {
    const { c, s, pos } = setup();
    const v = selectHoldings(c, pos, s.pending.intents, 'model', NO_FILTERS, { realized: true, held: true, pending: true }, { cls: '', l: 'x' });
    expect(v.rows).toHaveLength(10);
    expect(v).toMatchObject({ tag: 'MODEL', count: '10 positions', tMV: '$85,711.14', tGrades: '9 × A · 1 × C' });
    const txg = v.rows.find((r) => r.s === 'TXG')!;
    expect(txg).toMatchObject({ u: '+$2,925.45', uP: '+33.8%', c: '82', g: 'A' });
    const knsa = v.rows.find((r) => r.s === 'KNSA')!;
    expect(knsa).toMatchObject({ pend: 'SELL 39 @ open', pCls: 'info' });
  });

  it('filters by search, grade, band, sign and exit proximity', () => {
    const { c, s, pos } = setup();
    const all = selectHoldings(c, pos, s.pending.intents, 'model', NO_FILTERS, { realized: true, held: true, pending: true }, { cls: '', l: '' }).rows;
    expect(filterRows(all, { ...NO_FILTERS, q: 'geno' }).map((r) => r.s)).toEqual(['TXG']);
    expect(filterRows(all, { ...NO_FILTERS, grade: 'C' }).map((r) => r.s)).toEqual(['ROKU']);
    expect(filterRows(all, { ...NO_FILTERS, band: 'low' }).map((r) => r.s)).toEqual(['ORKA', 'KNSA']);
    expect(filterRows(all, { ...NO_FILTERS, near: true }).map((r) => r.s)).toEqual(['ORKA', 'KNSA']);
    expect(filterRows(all, { ...NO_FILTERS, sign: 'neg' }).every((r) => r._u < 0)).toBe(true);
  });

  it('shows the AMD drift side by side', () => {
    const { c, pos } = setup();
    const v = selectSide(c, pos);
    expect(v.drift).toBe('2.1%');
    expect(v.noteCls).toBe('warn');
    expect(v.rows.find((r) => r.s === 'AMD')).toMatchObject({ dSh: '−3', dCls: 'danger' });
  });

  it('builds the drawer for either book', () => {
    const { c, s, pos, pos1 } = setup();
    const m = selectDrawer(c, pos1('AMD'), pos, s.pending.intents, s.history.orders, 'model');
    expect(m).toMatchObject({ sh: '7', ed: 'Wed 23 Sep 2026', driftCls: 'warn' });
    expect(m.drift).toContain('trimmed to available cash');
    const a = selectDrawer(c, pos1('AMD'), pos, s.pending.intents, s.history.orders, 'account');
    expect(a.sh).toBe('4');
    expect(m.ords[0]).toMatchObject({ side: 'BUY', when: 'filled Wed 23 Sep' });
  });
});

describe('orders', () => {
  it('signs slippage by side so + is a cost', () => {
    expect(slippageBps('BUY', 100, 100.1)).toBeCloseTo(10);
    expect(slippageBps('SELL', 100, 99.9)).toBeCloseTo(10);
  });

  it('builds the history with lifecycle and adjustments', () => {
    const { c, s } = setup();
    const v = selectHistory(c, s.history, 'all');
    expect(v.hint).toBe('latest 16 of 44 orders · since Tue 18 Aug');
    expect(v.rows[0]).toMatchObject({ s: 'AMD', q: '4', hasAdj: true, adjS: 'adjusted 7 → 4', cid: 'trend-20260922-AMD-B1' });
    expect(v.rows[0].lc.map((x) => x.l)).toEqual(['Intent', 'Guardrails', 'Adjusted', 'Accepted', 'Filled', 'Reconciled']);
    expect(selectHistory(c, s.history, 'SELL').rows.every((r) => r.side === 'SELL')).toBe(true);
  });

  it('shows the twin’s modelled fill in Ghost (open + 5 bps)', () => {
    const { c, s } = setup({ env: 'ghost' });
    const v = selectHistory(c, s.history, 'all');
    expect(v.rows[0]).toMatchObject({ q: '7', op: '$621.81', fp: '$622.12', slip: '+5.0', hasAdj: false });
  });

  it('summarises round trips', () => {
    const { s } = setup();
    const v = selectRoundTrips(s.roundTrips.trips, s.roundTrips.fees);
    expect(v).toMatchObject({ win: '17.6%', winN: '3 wins of 17 round trips', tot: '−$12,661.26', pf: '0.11' });
  });
});

describe('compliance', () => {
  it('puts non-A cards first', () => {
    const { c, pos } = setup();
    expect(selectCards(c, pos)[0].s).toBe('ROKU');
  });

  it('filters the universe to the watchlist', () => {
    const { c, s, pos } = setup();
    const v = selectUniverse(c, pos, s.compliance, 'watch');
    expect(v.rows.map((r) => r.s)).toEqual(['LKQ', 'MRNA', 'ENPH', 'REGN', 'QRVO', 'SWKS']);
    expect(v.foot).toBe('Showing 6 of 319 · watchlist 6 · review-flagged 22 · excluded: 25');
  });
});

describe('health', () => {
  it('shows the stalled gate and the tripped data gate', () => {
    const { s } = setup({ env: 'ghost', health: 'stale' });
    const v = selectHealth(s.health, null);
    expect(v).toMatchObject({ pill: 'Degraded', pillCls: 'red' });
    expect(v.gate.l).toBe('Stalled — 4 failed sessions');
    expect(v.dg.checks[2]).toMatchObject({ g: '✕', l: 'Coverage at asof', v: '0.6%' });
    expect(v.dg.missing?.more).toBe('+305 more');
    expect(v.rows[0].c.slice(-4).map((x) => x.g)).toEqual(['✕', '✕', '✕', '✕']);
    expect(v.selT).toBe('Raw record · Cycle A · Thu 1 Oct · fail');
  });
});

describe('roadmap', () => {
  it('marks the ghost phase failing while Cycle A is stale', () => {
    const { s } = setup({ env: 'ghost', health: 'stale' });
    const v = selectRoadmap(s.roadmap, 'all');
    expect(v.phases[0].cls).toBe('cur fail');
    expect(v.phases[0].gates[0]).toMatchObject({ g: '✕', cls: 'danger' });
    expect(v.tasks.find((t) => t.id === 'G1')).toMatchObject({ soon: true, cd: 'in 2 days' });
    expect(selectRoadmap(s.roadmap, 'S').tasks.map((t) => t.id)).toEqual(['S1', 'S2', 'S3']);
  });
});
