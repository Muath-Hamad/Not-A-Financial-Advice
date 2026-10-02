// Read-only API client (docs/08 §10) and one TanStack Query hook per
// endpoint. Screens compose these; the cache dedupes shared reads (the chrome
// and the Overview both read holdings, pending orders and alerts).

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type {
  AlertsPayload, CompliancePayload, HealthPayload, HistoryPayload, HoldingDetailPayload, HoldingsPayload,
  OverviewPayload, PendingPayload, RoadmapPayload, RoundTripsPayload,
} from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' }, credentials: 'same-origin' });
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText} — ${path}`);
  return (await res.json()) as T;
}

/** The indexer pulls the ledger every 60 s (docs/08 §3.1); poll at the same pace until SSE lands. */
const POLL = 60_000;

export const keys = {
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
};

export const useOverview = () => useQuery({ queryKey: keys.overview, queryFn: () => getJson<OverviewPayload>('/api/overview'), refetchInterval: POLL });
export const useHoldings = () => useQuery({ queryKey: keys.holdings, queryFn: () => getJson<HoldingsPayload>('/api/holdings?book=model'), refetchInterval: POLL });
export const useHoldingDetail = (sym: string | null) => useQuery({ queryKey: keys.holding(sym ?? ''), queryFn: () => getJson<HoldingDetailPayload>('/api/holdings/' + encodeURIComponent(sym ?? '')), enabled: !!sym });
export const usePending = () => useQuery({ queryKey: keys.pending, queryFn: () => getJson<PendingPayload>('/api/orders/pending'), refetchInterval: POLL });
export const useHistory = () => useQuery({ queryKey: keys.history, queryFn: () => getJson<HistoryPayload>('/api/orders') });
export const useRoundTrips = () => useQuery({ queryKey: keys.roundTrips, queryFn: () => getJson<RoundTripsPayload>('/api/round-trips') });
export const useCompliance = () => useQuery({ queryKey: keys.compliance, queryFn: () => getJson<CompliancePayload>('/api/compliance') });
export const useAlerts = () => useQuery({ queryKey: keys.alerts, queryFn: () => getJson<AlertsPayload>('/api/alerts'), refetchInterval: POLL });
export const useHealth = () => useQuery({ queryKey: keys.health, queryFn: () => getJson<HealthPayload>('/api/health'), refetchInterval: POLL });
export const useRoadmap = () => useQuery({ queryKey: keys.roadmap, queryFn: () => getJson<RoadmapPayload>('/api/roadmap') });

export function useAckAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch('/api/alerts/' + encodeURIComponent(id) + '/ack', { method: 'POST', credentials: 'same-origin' });
      if (!res.ok) throw new ApiError(res.status, 'ack failed');
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.alerts }),
  });
}
