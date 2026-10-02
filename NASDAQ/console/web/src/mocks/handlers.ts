// MSW handlers for the v1 read API, served from the prototype fixtures.
// The active scenario is module state so the dev "Prototype states" panel
// and Storybook can switch it.

import { delay, http, HttpResponse } from 'msw';
import * as S from './scenario';

export interface MockState extends S.Scenario {
  /** Hold every screen read open forever (the Loading frame). */
  loading: boolean;
  /** Fail every read with a 503 (console API down). */
  apiDown: boolean;
}

let state: MockState = { ...S.defaultScenario(), loading: false, apiDown: false };
const acked: Record<string, true> = {};

export const getMockState = () => state;
export function setMockState(patch: Partial<MockState>) {
  state = { ...state, ...patch };
}
export function resetMockState(patch: Partial<MockState> = {}) {
  state = { ...S.defaultScenario(), loading: false, apiDown: false, ...patch };
  Object.keys(acked).forEach((k) => delete acked[k]);
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
  http.get('/api/alerts', () => serve(() => S.alerts(state, acked), { screen: false })),
  http.post('/api/alerts/:id/ack', ({ params }) => {
    acked[String(params.id)] = true;
    return new HttpResponse(null, { status: 204 });
  }),
  http.get('/api/health', () => serve(() => S.health(state))),
  http.get('/api/roadmap', () => serve(() => S.roadmap(state))),
];
