// App-wide state: the system context built from /api/overview, the chrome
// reads, theme, toasts, the ⌘K palette and the intent dispatcher.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAlerts, useHoldings, useOverview, usePending } from '@/api/client';
import type { Alert, Intent as OrderIntent, OverviewPayload, Position } from '@/api/types';
import { ctxFrom, type Ctx } from '@/domain/ctx';
import { sortAlerts } from '@/domain/core';
import type { Intent, Screen } from '@/domain/actions';

export type Theme = 'dark' | 'light';

interface ConsoleValue {
  /** null until /api/overview has answered once. */
  ctx: Ctx | null;
  overview: OverviewPayload | undefined;
  positions: Position[];
  intents: OrderIntent[];
  nextOpen: string;
  alerts: Alert[];
  /** The console API itself is unreachable (fetch failed, no data at all). */
  apiDown: boolean;
  screen: Screen;
  theme: Theme;
  setTheme: (t: Theme) => void;
  toast: string | null;
  showToast: (t: string) => void;
  palette: boolean;
  setPalette: (on: boolean) => void;
  drawer: string | null;
  openDrawer: (sym: string) => void;
  closeDrawer: () => void;
  dispatch: (i: Intent) => void;
  go: (screen: Screen, search?: Record<string, string>) => void;
}

const Console = createContext<ConsoleValue | null>(null);

export const SCREEN_PATH: Record<Screen, string> = {
  overview: '/', holdings: '/holdings', orders: '/orders', performance: '/performance', compliance: '/compliance',
  controls: '/controls', agent: '/agent', health: '/health', alerts: '/alerts', audit: '/audit', roadmap: '/roadmap',
  settings: '/settings', more: '/more',
};

export function screenOf(pathname: string): Screen {
  const seg = pathname.split('/')[1] || 'overview';
  return (seg in SCREEN_PATH ? seg : 'overview') as Screen;
}

const THEME_KEY = 'nafa.theme';

function readTheme(fallback: Theme): Theme {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === 'light' || v === 'dark' ? v : fallback;
  } catch {
    return fallback;
  }
}

/** `initialTheme` forces a theme (stories); without it the viewer's last choice is restored. */
export function ConsoleProvider({ children, initialTheme }: { children: ReactNode; initialTheme?: Theme }) {
  const ov = useOverview();
  const hq = useHoldings();
  const pq = usePending();
  const aq = useAlerts();
  const loc = useLocation();
  const navigate = useNavigate();
  const [search, setSearch] = useSearchParams();
  const [theme, setThemeState] = useState<Theme>(() => initialTheme ?? readTheme('dark'));
  const [toast, setToast] = useState<string | null>(null);
  const [palette, setPalette] = useState(false);
  const toastTimer = useRef<number | undefined>(undefined);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    try { localStorage.setItem(THEME_KEY, t); } catch { /* private mode: theme just isn't remembered */ }
  }, []);

  const showToast = useCallback((t: string) => {
    setToast(t);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);
  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  const screen = screenOf(loc.pathname);
  const routeSym = loc.pathname.startsWith('/holdings/') ? decodeURIComponent(loc.pathname.split('/')[2] || '') : null;
  const drawer = routeSym || search.get('h');

  const loading = hq.isPending || pq.isPending;
  const ctx = useMemo(() => (ov.data ? ctxFrom(ov.data, loading) : null), [ov.data, loading]);
  const alerts = useMemo(() => sortAlerts(aq.data?.alerts ?? []), [aq.data]);

  const go = useCallback((s: Screen, extra?: Record<string, string>) => {
    if (s === 'controls' && ctx && ctx.role !== 'owner') {
      showToast('Read-only viewer — Controls are owner-only');
      return;
    }
    let path = SCREEN_PATH[s];
    const q = new URLSearchParams();
    if (extra?.tab) path += '/' + extra.tab;
    Object.entries(extra ?? {}).forEach(([k, v]) => { if (k !== 'tab') q.set(k, v); });
    setPalette(false);
    navigate(path + (q.toString() ? '?' + q : ''));
  }, [ctx, navigate, showToast]);

  const openDrawer = useCallback((sym: string) => {
    setPalette(false);
    if (screen === 'holdings') navigate('/holdings/' + encodeURIComponent(sym) + loc.search);
    else {
      const next = new URLSearchParams(search);
      next.set('h', sym);
      setSearch(next);
    }
  }, [screen, navigate, loc.search, search, setSearch]);

  const closeDrawer = useCallback(() => {
    if (routeSym) navigate('/holdings' + loc.search);
    else {
      const next = new URLSearchParams(search);
      next.delete('h');
      setSearch(next);
    }
  }, [routeSym, navigate, loc.search, search, setSearch]);

  const dispatch = useCallback((i: Intent) => {
    switch (i.kind) {
      case 'nav': return go(i.screen, i.search);
      case 'drawer': return openDrawer(i.symbol);
      case 'toast': return showToast(i.text);
      case 'control':
      case 'preflight':
        if (ctx && ctx.role !== 'owner') return showToast('Read-only viewer — controls are owner-only');
        return showToast('Read-only build (M0) — controls arrive with milestone M1');
    }
  }, [go, openDrawer, showToast, ctx]);

  const value: ConsoleValue = {
    ctx,
    overview: ov.data,
    positions: hq.data?.positions ?? [],
    intents: pq.data?.intents ?? [],
    nextOpen: pq.data?.nextOpen ?? ov.data?.asof ?? '',
    alerts,
    apiDown: ov.isError && !ov.data,
    screen,
    theme, setTheme,
    toast, showToast,
    palette, setPalette,
    drawer, openDrawer, closeDrawer,
    dispatch, go,
  };
  return <Console.Provider value={value}>{children}</Console.Provider>;
}

export function useConsole(): ConsoleValue {
  const v = useContext(Console);
  if (!v) throw new Error('useConsole outside ConsoleProvider');
  return v;
}

/** The system context, for screens that only render once it exists. */
export function useCtx(): Ctx {
  const { ctx } = useConsole();
  if (!ctx) throw new Error('useCtx before /api/overview answered');
  return ctx;
}
