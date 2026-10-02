// Settings, the phone "More" list, and placeholders for screens that arrive
// in later milestones (docs/08 §12).

import { useConsole, useCtx } from '@/app/console';
import { openAlerts } from '@/domain/core';
import type { Screen } from '@/domain/actions';
import { Icon } from '@/components/icons';
import { Chip, Empty, PageHeader, Seg } from '@/components/ui';

export function Settings() {
  const { theme, setTheme } = useConsole();
  const ctx = useCtx();
  return (
    <div className="page">
      <PageHeader title="Settings" sub="Users, two-factor, notifications and display" />
      <div className="g12">
        <section className="panel c6">
          <div className="ph"><h3>Users &amp; roles</h3><span className="sp" />{ctx.role === 'owner' && <button type="button" className="btn sm" disabled title="Arrives with authentication in M1">Invite viewer…</button>}</div>
          <div className="att">
            <div className="att-i"><span className="avatar">M</span><div className="att-t"><span className="b">M</span><span className="s">Owner · every control</span></div><Chip>Owner · all controls</Chip></div>
            <div className="att-i"><span className="avatar">SR</span><div className="att-t"><span className="b">Sharia reviewer</span><span className="s">invited · read-only: Compliance, Holdings, Orders history</span></div><Chip cls="info">Viewer</Chip></div>
          </div>
        </section>
        <section className="panel c6">
          <div className="ph"><h3>Two-factor authentication</h3><Chip cls="warn" style={{ marginLeft: 'auto' }}>Arrives in M1</Chip></div>
          <div className="pb">
            <dl className="kv" style={{ margin: 0 }}>
              <dt>Method</dt><dd>Authenticator app (TOTP, 6 digits)</dd>
              <dt>Step-up window</dt><dd>5 minutes · then the code is asked again</dd>
              <dt>Typed confirmation</dt><dd>STOP · FLATTEN · the symbol · PAUSE</dd>
              <dt>Recovery codes</dt><dd>issued at enrolment</dd>
            </dl>
          </div>
        </section>
        <section className="panel c6">
          <div className="ph"><h3>Notifications</h3><Chip cls="warn" style={{ marginLeft: 'auto' }}>Arrives in M2</Chip></div>
          <div className="pb col" style={{ gap: 0 }}>
            <div className="limit"><span>P1 · push to phone (ntfy)</span><span className="xs muted">always on once configured</span></div>
            <div className="limit"><span>P2 · evening digest 18:30 ET</span><span className="xs muted">planned</span></div>
            <div className="limit"><span>Night held · remind at 08:45 ET</span><span className="xs muted">planned</span></div>
          </div>
        </section>
        <section className="panel c6">
          <div className="ph"><h3>Display</h3></div>
          <div className="pb col" style={{ gap: 0 }}>
            <div className="limit"><span>Theme</span><Seg label="Theme" value={theme} onChange={setTheme} items={[{ k: 'light', l: 'Light' }, { k: 'dark', l: 'Dark' }]} /></div>
            <div className="limit"><span>Time zone</span><span className="xs dim">Market times always in ET</span></div>
          </div>
        </section>
      </div>
    </div>
  );
}

export function More() {
  const { go, alerts, theme, setTheme } = useConsole();
  const ctx = useCtx();
  const open = openAlerts(alerts);
  const items: [Screen, string, string][] = [
    ['performance', 'Performance', 'Equity · returns · attribution'], ['compliance', 'Compliance', 'Sharia cards · re-screens'], ['agent', 'Agent', 'Parameters · journal'],
    ['health', 'Health', 'Cycles · data gate · broker'], ['alerts', 'Alerts', open.length + ' open'], ['audit', 'Audit log', 'Every control change'],
    ['roadmap', 'Roadmap', 'Phases · D1–D8 · tasks'], ['settings', 'Settings', 'Users · 2FA · display'],
  ];
  return (
    <div className="page">
      <div className="page-h"><h1>More</h1></div>
      <section className="panel">
        <div className="att">
          {items.map(([k, l, s]) => {
            const badge = k === 'alerts' && open.length ? String(open.length) : k === 'health' && (ctx.data === 'stale' || ctx.data === 'error') ? '!' : '';
            return (
              <button key={k} type="button" className="att-i mbtn" onClick={() => go(k)}>
                <span className="b sp">{l}</span><span className="xs muted">{s}</span>{badge && <span className="cnt red">{badge}</span>}<Icon name="chevron" className="s14 muted" />
              </button>
            );
          })}
        </div>
      </section>
      <section className="panel"><div className="pb row"><span className="sm sp">Theme</span><Seg label="Theme" value={theme} onChange={setTheme} items={[{ k: 'dark', l: 'Dark' }, { k: 'light', l: 'Light' }]} /></div></section>
    </div>
  );
}

const LATER: Partial<Record<Screen, [string, string, string]>> = {
  performance: ['Performance', 'M2', 'Equity and drawdown, metrics against the OOS reference, monthly returns, attribution and execution quality. The equity chart is already on the Overview.'],
  controls: ['Controls', 'M1', 'The executive desk: pause entries, STOP, stop & flatten, resume with the preflight checklist, holding overrides — each through impact preview → reason → TOTP → result, committed to the ledger.'],
  agent: ['Agent', 'M3', 'Parameters against their bounds, regime, the mood and sentiment journal, the adaptation trail and confidence calibration.'],
  alerts: ['Alerts', 'M2', 'The P1/P2 inbox with acknowledge and resolve, linked to the source cycle and GitHub issue, plus ntfy push. Open alerts already show in the top bar and on the Overview.'],
  audit: ['Audit log', 'M1', 'Every control change and command — git log of controls.json and halt.json plus console records, with before → after, reason and commit.'],
};

export function Later({ screen }: { screen: Screen }) {
  const [title, m, p] = LATER[screen] ?? [screen, 'later', ''];
  const { go } = useConsole();
  return (
    <div className="page">
      <PageHeader title={title} sub={'Arrives with milestone ' + m + ' (docs/08 §12) — this build is the read-only M0'} />
      <section className="panel">
        <Empty icon="clock" title={title + ' arrives in ' + m} actions={<button type="button" className="btn" onClick={() => go('roadmap')}>View roadmap</button>}>{p}</Empty>
      </section>
    </div>
  );
}
