import { describe, expect, it } from 'vitest';
import { defaultControls, defaultScenario, snapshot, type Scenario } from '@/mocks/scenario';
import * as D from '@/mocks/desk';
import { filterAlerts } from '@/screens/Alerts';
import { resCls } from '@/screens/Audit';
import { ctxFrom } from './ctx';
import { categoryFor, selectControls } from './controls';
import { heatCell, metricText, sn, selectAgent, selectExecution, selectPerformance, waterfall } from './performance';

function setup(patch: Partial<Scenario> = {}) {
  const sc = { ...defaultScenario(), ...patch };
  const s = snapshot(sc);
  return { sc, c: ctxFrom(s.overview), pos: s.holdings.positions };
}

describe('controls desk (M1)', () => {
  it('offers pause, STOP and flatten while running', () => {
    const { sc, c, pos } = setup();
    const ct = selectControls(c, D.controls(sc), pos);
    expect([ct.b1.action, ct.b2.action, ct.b3.action]).toEqual(['pause', 'stop', 'flatten']);
    expect(ct.big).toBe('RUNNING');
    expect(ct.ovr).toHaveLength(pos.length);
  });

  it('swaps STOP for resume (preflight) when stopped, and pause for resume entries when paused', () => {
    const st = setup({ trading: 'stopped' });
    expect(selectControls(st.c, D.controls(st.sc), st.pos).b2.action).toBe('resume');
    const pa = setup({ trading: 'paused' });
    expect(selectControls(pa.c, D.controls(pa.sc), pa.pos).b1.action).toBe('resume_entries');
  });

  it('marks locked, trimmed and force-exited holdings', () => {
    const { sc, c, pos } = setup({ controls: { ...defaultControls(), lockedSymbols: ['TXG'], forcedExits: ['ROKU'], manualOrders: [{ symbol: 'MU', shares: 10, pct: 50 }] } });
    const ct = selectControls(c, D.controls(sc), pos);
    const row = (s: string) => ct.ovr.find((o) => o.s === s)!;
    expect(row('TXG').status).toBe('Locked — agent skips');
    expect(row('ROKU').forced).toBe(true);
    expect(row('MU').status).toBe('Trim 10 sh queued');
  });

  it('shows the halt diff only while halted', () => {
    const h = setup({ trading: 'halted' });
    expect(selectControls(h.c, D.controls(h.sc), h.pos).haltDiffs).toEqual([{ symbol: 'ROKU', expected: 75, actual: 74 }]);
    const r = setup();
    expect(selectControls(r.c, D.controls(r.sc), r.pos).halted).toBe(false);
  });

  it('defaults the reason category by action', () => {
    expect(categoryFor('force_exit')).toBe('Compliance');
    expect(categoryFor('stop')).toBe('Risk');
    expect(categoryFor('rerun')).toBe('Operational');
  });

  it('asks for the typed word on destructive actions only', () => {
    const { sc } = setup();
    expect(D.preview(sc, 'stop', {}).word).toBe('STOP');
    expect(D.preview(sc, 'force_exit', { symbol: 'TXG' }).word).toBe('TXG');
    expect(D.preview(sc, 'pause', {}).word).toBeNull();
    expect(D.preview(sc, 'lock', { symbol: 'ZZZZ' }).errors).toEqual(['ZZZZ is not held']);
  });

  it('blocks resume until every preflight check passes', () => {
    const { sc } = setup({ trading: 'stopped' });
    expect(D.preflight(sc, {}, '').ok).toBe(false);
    const all = D.preflight(sc, { ack: true, cyca: true }, 'checked the feed');
    expect(all.checks.find((x) => x.id === 'ack')!.pass).toBe(true);
  });
});

describe('performance (M2)', () => {
  it('formats metrics by unit and never invents a value', () => {
    expect(metricText(-0.112, 'pct')).toBe('−11.2%');
    expect(metricText(1.224, 'ratio')).toBe('1.22');
    expect(metricText(-4.087, 'ratio')).toBe('−4.09');
    expect(sn(-0.001, 2)).toBe('0.00');
    expect(metricText(44, 'count')).toBe('44');
    expect(metricText(null, 'pct')).toBe('—');
  });

  it('walks the waterfall from $0 to the total', () => {
    const wf = waterfall([{ label: 'A', value: 100 }, { label: 'B', value: -40 }]);
    expect(wf.total).toBe(60);
    expect(wf.bars.map((b) => b.l)).toEqual(['A', 'B', 'Total']);
    expect(wf.bars[1].cls).toBe('neg');
    expect(waterfall([]).bars).toEqual([]);
  });

  it('tints the heat map by sign and leaves gaps blank', () => {
    expect(heatCell(null).cls).toBe('na');
    expect(heatCell(0.05).bg).toContain('var(--pos)');
    expect(heatCell(-0.05).bg).toContain('var(--neg)');
  });

  it('has no account columns or execution in Ghost', () => {
    const { sc } = setup({ env: 'ghost' });
    const p = D.performance(sc);
    expect(selectPerformance(p).metrics.find((m) => m.key === 'sharpe')!.a).toBe('—');
    expect(selectExecution(p)).toBeNull();
  });

  it('flags fills outside ±10 bps', () => {
    const ex = selectExecution(D.performance(setup().sc))!;
    expect(ex.pts.some((p) => p.cls === 'out')).toBe(true);
    expect(Number(ex.out)).toBeGreaterThan(0);
  });
});

describe('agent (M3)', () => {
  it('places parameters inside their bounds and shows OOS calibration', () => {
    const ag = selectAgent(D.agent(setup().sc));
    expect(ag.params.every((p) => p.pos == null || (p.pos >= 0 && p.pos <= 100))).toBe(true);
    expect(ag.cal.map((c) => c.oosHit)).toEqual(['68%', '23%', '0%']);
    expect(ag.calNote).toContain('too small to judge');
  });

  it('says adapt() is paused instead of a next date', () => {
    const ag = selectAgent(D.agent(setup({ controls: { ...defaultControls(), pauseAdapt: true } }).sc));
    expect(ag.adaptL).toBe('adapt() paused');
    expect(ag.trail[0].d).toContain('Paused');
  });
});

describe('alerts and audit', () => {
  it('filters the inbox', () => {
    const alerts = [
      { id: '1', priority: 'P1' as const, title: '', detail: '', source: '', githubIssue: null, raisedAt: '', status: 'open' as const, note: '' },
      { id: '2', priority: 'P2' as const, title: '', detail: '', source: '', githubIssue: null, raisedAt: '', status: 'resolved' as const, note: 'ok' },
    ];
    expect(filterAlerts(alerts, 'open').map((a) => a.id)).toEqual(['1']);
    expect(filterAlerts(alerts, 'resolved').map((a) => a.id)).toEqual(['2']);
    expect(filterAlerts(alerts, 'all')).toHaveLength(2);
  });

  it('colours audit results', () => {
    expect(resCls('Not applied')).toBe('danger');
    expect(resCls('Applied (dry run)')).toBe('warn');
    expect(resCls('Applied')).toBe('pos');
  });
});
