// MSW handlers for the v1 read API, served from the prototype fixtures.
// The active scenario is module state so the dev "Prototype states" panel
// and Storybook can switch it.

import { delay, http, HttpResponse } from 'msw';
import * as S from './scenario';
import * as D from './desk';
import type { AuditRow } from '@/api/types';
import type { ControlAction } from '@/domain/actions';

export interface MockState extends S.Scenario {
  /** Hold every screen read open forever (the Loading frame). */
  loading: boolean;
  /** Fail every read with a 503 (console API down). */
  apiDown: boolean;
  /** The next control apply fails at its last step ("Not applied"). */
  failApply?: boolean;
  /** /api/auth/me answers 401 (the sign-in frame). */
  signedOut?: boolean;
}

let state: MockState = { ...S.defaultScenario(), loading: false, apiDown: false };
const acked: Record<string, true> = {};
const resolved: Record<string, string> = {};
let auditLog: AuditRow[] = [];

export const getMockState = () => state;
export function setMockState(patch: Partial<MockState>) {
  state = { ...state, ...patch };
}
export function resetMockState(patch: Partial<MockState> = {}) {
  state = { ...S.defaultScenario(), loading: false, apiDown: false, ...patch };
  Object.keys(acked).forEach((k) => delete acked[k]);
  Object.keys(resolved).forEach((k) => delete resolved[k]);
  auditLog = [];
}

async function serve<T>(build: () => T, opts: { screen?: boolean } = { screen: true }) {
  if (state.apiDown) return HttpResponse.json({ detail: 'console API unavailable' }, { status: 503 });
  if (state.loading && opts.screen) await delay('infinite');
  await delay(state.loading ? 0 : 120);
  return HttpResponse.json(build() as object);
}

export const handlers = [
  http.get('/api/overview', () => serve(() => S.overview(state), { screen: false })),
  http.get('/api/holdings', () => serve(() => S.holdings(state))),
  http.get('/api/holdings/:sym', ({ params }) => {
    const d = S.holdingDetail(state, String(params.sym));
    return d ? serve(() => d) : HttpResponse.json({ detail: 'not held' }, { status: 404 });
  }),
  http.get('/api/orders/pending', () => serve(() => S.pending(state))),
  http.get('/api/orders', () => serve(() => S.history(state))),
  http.get('/api/round-trips', () => serve(() => S.roundTrips(state))),
  http.get('/api/compliance', () => serve(() => S.compliance())),
  http.get('/api/alerts', () => serve(() => {
    const p = S.alerts(state, acked);
    return { alerts: p.alerts.map((a) => (resolved[a.id] != null ? { ...a, status: 'resolved' as const, note: resolved[a.id] } : a)) };
  }, { screen: false })),
  http.post('/api/alerts/:id/ack', ({ params }) => {
    acked[String(params.id)] = true;
    return new HttpResponse(null, { status: 204 });
  }),
  http.post('/api/alerts/:id/resolve', async ({ params, request }) => {
    const b = (await request.json()) as { note?: string };
    resolved[String(params.id)] = b.note ?? '';
    return new HttpResponse(null, { status: 204 });
  }),
  http.get('/api/auth/me', () => (state.signedOut ? HttpResponse.json({ detail: 'sign in' }, { status: 401 }) : serve(() => D.me(state), { screen: false }))),
  http.post('/api/auth/login', () => { state = { ...state, signedOut: false }; return HttpResponse.json({ csrf: 'mock-csrf' }); }),
  http.post('/api/auth/logout', () => new HttpResponse(null, { status: 204 })),
  http.get('/api/controls', () => serve(() => D.controls(state))),
  http.post('/api/controls/preview', async ({ request }) => {
    const b = (await request.json()) as { action: ControlAction; params: Record<string, unknown> };
    return serve(() => D.preview(state, b.action, b.params ?? {}), { screen: false });
  }),
  http.post('/api/controls/preflight', async ({ request }) => {
    const b = (await request.json()) as { ticks: Record<string, boolean>; note: string };
    return serve(() => D.preflight(state, b.ticks ?? {}, b.note ?? ''), { screen: false });
  }),
  http.post('/api/controls/apply', async ({ request }) => {
    const b = (await request.json()) as { action: ControlAction; params: Record<string, unknown>; reason: string; category: string };
    const pv = D.preview(state, b.action, b.params ?? {});
    if (pv.errors.length) return HttpResponse.json({ detail: pv.errors.join('; ') }, { status: 422 });
    const ok = !state.failApply;
    await delay(600);
    auditLog = [{ t: 'Fri 25 Sep 18:10', at: '2026-09-25T22:10:00Z', actor: 'owner', act: pv.title, ba: pv.pending, reason: '[' + b.category + '] ' + b.reason, eff: pv.eff, sha: ok ? '9a4e1c7' : '—', res: ok ? 'Applied' : 'Not applied' }, ...auditLog];
    if (ok) state = { ...state, ...D.applyPatch(state, b.action, b.params ?? {}) };
    return HttpResponse.json(D.applyResult(pv, ok));
  }),
  http.get('/api/audit', () => serve(() => D.audit(auditLog))),
  http.get('/api/performance', () => serve(() => D.performance(state))),
  http.get('/api/agent', () => serve(() => D.agent(state))),
  http.get('/api/review', () => serve(() => ({ months: ['2026-08', '2026-09'] }), { screen: false })),
  http.post('/api/sync', () => HttpResponse.json({ changed: false })),
  http.get('/api/health', () => serve(() => S.health(state))),
  http.get('/api/roadmap', () => serve(() => S.roadmap(state))),
];
