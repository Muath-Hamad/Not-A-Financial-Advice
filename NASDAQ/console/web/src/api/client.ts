// API client (docs/08 §10) and one TanStack Query hook per endpoint. Screens
// compose these; the cache dedupes shared reads. POSTs carry the session's
// CSRF token (docs/08 §9); a 401 anywhere sends the app to the sign-in page.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  AgentPayload, AlertsPayload, ApplyResult, AuditPayload, CompliancePayload, ControlsPayload, HealthPayload, HistoryPayload,
  HoldingDetailPayload, HoldingsPayload, MePayload, OverviewPayload, PendingPayload, PerformancePayload, PreflightPayload, Preview,
  RoadmapPayload, RoundTripsPayload,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

let csrf = '';
export const setCsrf = (t: string) => { csrf = t; };

async function parse(res: Response, path: string) {
  const text = await res.text();
  let body: unknown = undefined;
  try { body = text ? JSON.parse(text) : undefined; } catch { body = text; }
  if (!res.ok) {
    const detail = (body as { detail?: string } | undefined)?.detail;
    throw new ApiError(res.status, detail || `${res.status} ${res.statusText} — ${path}`, body);
  }
  return body;
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
  return (await parse(res, path)) as T;
}

export async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-CSRF-Token': csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await parse(res, path)) as T;
}

/** The indexer pulls the ledger every 60 s (docs/08 §3.1); poll at the same pace. */
const POLL = 60_000;

export const keys = {
  me: ['me'] as const,
  overview: ['overview'] as const,
  holdings: ['holdings'] as const,
  holding: (s: string) => ['holding', s] as const,
  pending: ['orders', 'pending'] as const,
  history: ['orders', 'history'] as const,
  roundTrips: ['round-trips'] as const,
  compliance: ['compliance'] as const,
  alerts: ['alerts'] as const,
  health: ['health'] as const,
  roadmap: ['roadmap'] as const,
  controls: ['controls'] as const,
  audit: ['audit'] as const,
  performance: ['performance'] as const,
  agent: ['agent'] as const,
  review: ['review'] as const,
};

const noRetryOn401 = (n: number, e: unknown) => !(e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 404)) && n < 1;

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: () => getJson<MePayload>('/api/auth/me'), retry: noRetryOn401, staleTime: 60_000 });
export const useOverview = (enabled = true) => useQuery({ queryKey: keys.overview, queryFn: () => getJson<OverviewPayload>('/api/overview'), refetchInterval: POLL, enabled, retry: noRetryOn401 });
export const useHoldings = (enabled = true) => useQuery({ queryKey: keys.holdings, queryFn: () => getJson<HoldingsPayload>('/api/holdings?book=model'), refetchInterval: POLL, enabled, retry: noRetryOn401 });
export const useHoldingDetail = (sym: string | null) => useQuery({ queryKey: keys.holding(sym ?? ''), queryFn: () => getJson<HoldingDetailPayload>('/api/holdings/' + encodeURIComponent(sym ?? '')), enabled: !!sym });
export const usePending = (enabled = true) => useQuery({ queryKey: keys.pending, queryFn: () => getJson<PendingPayload>('/api/orders/pending'), refetchInterval: POLL, enabled, retry: noRetryOn401 });
export const useHistory = () => useQuery({ queryKey: keys.history, queryFn: () => getJson<HistoryPayload>('/api/orders') });
export const useRoundTrips = () => useQuery({ queryKey: keys.roundTrips, queryFn: () => getJson<RoundTripsPayload>('/api/round-trips') });
export const useCompliance = () => useQuery({ queryKey: keys.compliance, queryFn: () => getJson<CompliancePayload>('/api/compliance') });
export const useAlerts = (enabled = true) => useQuery({ queryKey: keys.alerts, queryFn: () => getJson<AlertsPayload>('/api/alerts'), refetchInterval: POLL, enabled, retry: noRetryOn401 });
export const useHealth = () => useQuery({ queryKey: keys.health, queryFn: () => getJson<HealthPayload>('/api/health'), refetchInterval: POLL });
export const useRoadmap = () => useQuery({ queryKey: keys.roadmap, queryFn: () => getJson<RoadmapPayload>('/api/roadmap') });
export const useControls = (enabled = true) => useQuery({ queryKey: keys.controls, queryFn: () => getJson<ControlsPayload>('/api/controls'), refetchInterval: POLL, enabled });
export const useAudit = () => useQuery({ queryKey: keys.audit, queryFn: () => getJson<AuditPayload>('/api/audit') });
export const usePerformance = () => useQuery({ queryKey: keys.performance, queryFn: () => getJson<PerformancePayload>('/api/performance') });
export const useAgent = () => useQuery({ queryKey: keys.agent, queryFn: () => getJson<AgentPayload>('/api/agent') });
export const useReviewMonths = () => useQuery({ queryKey: keys.review, queryFn: () => getJson<{ months: string[] }>('/api/review') });

export const preview = (action: string, params: Record<string, unknown>) => postJson<Preview>('/api/controls/preview', { action, params });
export const apply = (body: Record<string, unknown>) => postJson<ApplyResult>('/api/controls/apply', body);
export const preflight = (ticks: Record<string, boolean>, note: string) => postJson<PreflightPayload>('/api/controls/preflight', { ticks, note });

export function useAlertAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, kind, note }: { id: string; kind: 'ack' | 'resolve'; note?: string }) => {
      await postJson('/api/alerts/' + encodeURIComponent(id) + '/' + kind, kind === 'resolve' ? { note } : {});
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.alerts }),
  });
}

/** Everything a control change can move: refetch it all after an apply. */
export function invalidateAfterControl(qc: ReturnType<typeof useQueryClient>) {
  for (const k of [keys.overview, keys.controls, keys.pending, keys.holdings, keys.alerts, keys.audit, keys.health]) qc.invalidateQueries({ queryKey: k });
}
