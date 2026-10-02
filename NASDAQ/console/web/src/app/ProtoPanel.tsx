// Mock-mode only: switch the MSW scenario (environment, data health, trading
// state, role, theme) like the prototype's "Prototype states" panel.

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { getMockState, resetMockState, setMockState, type MockState } from '@/mocks/handlers';
import { Seg } from '@/components/ui';
import { Icon } from '@/components/icons';
import { useConsole } from './console';

type Data = 'loaded' | 'loading' | 'empty' | 'stale' | 'error';

export function ProtoPanel() {
  const qc = useQueryClient();
  const { theme, setTheme } = useConsole();
  const [open, setOpen] = useState(false);
  const [, bump] = useState(0);
  const st = getMockState();
  const apply = (patch: Partial<MockState>) => {
    setMockState(patch);
    bump((n) => n + 1);
    qc.resetQueries();
  };
  const data: Data = st.loading ? 'loading' : st.health;
  if (!open) {
    return (
      <button type="button" className="proto-tag proto-launch" onClick={() => setOpen(true)}>
        PROTOTYPE STATES
      </button>
    );
  }
  return (
    <div className="proto" role="dialog" aria-label="Prototype states">
      <div className="row"><span className="proto-tag">MOCK API · PROTOTYPE STATES</span><span className="sp" /><button type="button" className="btn ghost sm icon" onClick={() => setOpen(false)} aria-label="Close prototype panel"><Icon name="close" className="s14" /></button></div>
      <Group l="Environment"><Seg label="Environment" value={st.env} onChange={(env) => apply({ env })} items={[{ k: 'ghost', l: 'GHOST' }, { k: 'paper', l: 'PAPER' }, { k: 'live', l: 'LIVE' }]} /></Group>
      <Group l="Data state">
        <Seg<Data> label="Data state" value={data} onChange={(d) => apply(d === 'loading' ? { loading: true } : { loading: false, health: d })}
          items={[{ k: 'loaded', l: 'Loaded' }, { k: 'loading', l: 'Loading' }, { k: 'empty', l: 'Empty' }, { k: 'stale', l: 'Stale' }, { k: 'error', l: 'Error' }]} />
      </Group>
      <Group l="Trading state"><Seg label="Trading state" value={st.trading} onChange={(trading) => apply({ trading, released: false, haltCleared: false })} items={[{ k: 'running', l: 'Running' }, { k: 'paused', l: 'Paused' }, { k: 'held', l: 'Held' }, { k: 'halted', l: 'Halted' }, { k: 'stopped', l: 'Stopped' }]} /></Group>
      <Group l="Role"><Seg label="Role" value={st.role} onChange={(role) => apply({ role })} items={[{ k: 'owner', l: 'Owner' }, { k: 'viewer', l: 'Viewer' }]} /></Group>
      <Group l="Theme"><Seg label="Theme" value={theme} onChange={setTheme} items={[{ k: 'dark', l: 'Dark' }, { k: 'light', l: 'Light' }]} /></Group>
      <Group l="Console API"><Seg label="Console API" value={st.apiDown ? 'down' : 'up'} onChange={(v) => apply({ apiDown: v === 'down' })} items={[{ k: 'up', l: 'Reachable' }, { k: 'down', l: 'Down (503)' }]} /></Group>
      <button type="button" className="btn sm" onClick={() => { resetMockState(); bump((n) => n + 1); qc.resetQueries(); }}>Reset scenario</button>
    </div>
  );
}

function Group({ l, children }: { l: string; children: React.ReactNode }) {
  return <div className="col gap4"><span className="xs muted">{l}</span>{children}</div>;
}
