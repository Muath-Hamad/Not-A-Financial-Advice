// UI intents a selector can attach to a button. Selectors stay pure; the
// shell turns an intent into navigation, a drawer, a toast or (from M1) the
// confirm modal.

export type Screen =
  | 'overview' | 'holdings' | 'orders' | 'performance' | 'compliance' | 'controls'
  | 'agent' | 'health' | 'alerts' | 'audit' | 'roadmap' | 'glossary' | 'settings' | 'more';

export type ControlAction =
  | 'stop' | 'flatten' | 'pause' | 'resume_entries' | 'resume' | 'force_exit' | 'lock' | 'unlock'
  | 'trim' | 'release' | 'clear_halt' | 'adapt' | 'gross' | 'rerun' | 'unexclude' | 'cancel_manual';

export type Intent =
  | { kind: 'nav'; screen: Screen; search?: Record<string, string> }
  | { kind: 'drawer'; symbol: string }
  | { kind: 'control'; action: ControlAction; symbol?: string; params?: Record<string, unknown> }
  | { kind: 'preflight' }
  | { kind: 'toast'; text: string };

export const nav = (screen: Screen, search?: Record<string, string>): Intent => ({ kind: 'nav', screen, search });
export const drawer = (symbol: string): Intent => ({ kind: 'drawer', symbol });
export const control = (action: ControlAction, symbol?: string, params?: Record<string, unknown>): Intent => ({ kind: 'control', action, symbol, params });
export const toast = (text: string): Intent => ({ kind: 'toast', text });
