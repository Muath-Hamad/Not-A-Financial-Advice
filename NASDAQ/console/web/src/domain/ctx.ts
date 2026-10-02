import type { Clock, ControlsState, DataHealth, Env, Facts, OverviewPayload, Role, TradingState } from '@/api/types';

/** The prototype's `dataState`: server health plus the client-only `loading`. */
export type DataState = DataHealth | 'loading';

/**
 * Everything the selectors need to know about the system, independent of
 * which screen is open. Built once from GET /api/overview.
 */
export interface Ctx {
  env: Env;
  data: DataState;
  trading: TradingState;
  role: Role;
  released: boolean;
  haltCleared: boolean;
  stopAt: string | null;
  flatten: boolean;
  clock: Clock;
  /** Dated facts from the server (no copy hard-codes a date). */
  facts: Facts;
  /** Model book as-of session (ISO). */
  asof: string;
  controls: ControlsState;
  /** Model book equity and cash (the twin). */
  equity: number;
  cash: number;
  /** Account cash, or null in Ghost. */
  accountCash: number | null;
}

export function ctxFrom(o: OverviewPayload, loading = false): Ctx {
  return {
    env: o.system.env,
    data: loading ? 'loading' : o.system.health,
    trading: o.system.trading,
    role: o.me.role,
    released: o.system.released,
    haltCleared: o.system.haltCleared,
    stopAt: o.system.stopAt,
    flatten: o.system.flatten,
    clock: o.system.clock,
    facts: o.system.facts,
    asof: o.asof,
    controls: o.controls,
    equity: o.equity,
    cash: o.cash,
    accountCash: o.accountCash,
  };
}

export const isGhost = (c: Ctx) => c.env === 'ghost';
export const isOwner = (c: Ctx) => c.role === 'owner';
