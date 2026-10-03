// Settings and the phone "More" list.

import { useQueryClient } from '@tanstack/react-query';
import { postJson, useControls } from '@/api/client';
import { useConsole, useCtx } from '@/app/console';
import { openAlerts } from '@/domain/core';
import type { Screen } from '@/domain/actions';
import { Icon } from '@/components/icons';
import { Chip, PageHeader, Seg } from '@/components/ui';
import { cx } from '@/lib/format';
import { T } from '@/glossary/Term';

export function Settings() {
  const { theme, setTheme, me } = useConsole();
  const ctx = useCtx();
  const qc = useQueryClient();
  const cq = useControls(ctx.role === 'owner');
  const write = cq.data?.write;
  const signOut = async () => {
    await postJson('/api/auth/logout').catch(() => undefined);
    qc.clear();
    window.location.assign('/');
  };
  const user = me?.user ?? '—';
  return (
    <div className="page">
      <PageHeader title="Settings" sub="Session, two-factor, notifications and display" />
      <div className="g12">
        <section className="panel c6">
          <div className="ph"><h3>Session</h3><span className="sp" />{me?.auth && <button type="button" className="btn sm" onClick={signOut}>Sign out</button>}</div>
          <div className="att">
            <div className="att-i"><span className="avatar">{user.slice(0, 2).toUpperCase()}</span><div className="att-t"><span className="b">{user}</span><span className="s">{ctx.role === 'owner' ? 'Owner · every control' : 'Viewer · read-only'}</span></div><Chip cls={ctx.role === 'owner' ? undefined : 'info'}>{ctx.role === 'owner' ? 'Owner' : 'Viewer'}</Chip></div>
          </div>
          <div className="pf"><span className="muted">Users are added on the box: <span className="mono">python -m nafa_console.users add NAME --role owner|viewer</span> (prints the authenticator QR secret once).</span></div>
        </section>
        <section className="panel c6">
          <div className="ph"><h3>Two-factor authentication</h3><Chip cls={me?.auth ? 'pos' : 'warn'} style={{ marginLeft: 'auto' }}>{me?.auth ? 'On' : 'Off (CONSOLE_AUTH=off)'}</Chip></div>
          <div className="pb">
            <dl className="kv" style={{ margin: 0 }}>
              <dt>Method</dt><dd>Authenticator app (<T k="totp">TOTP</T>, 6 digits)</dd>
              <dt><T k="stepUp">Step-up</T></dt><dd>Every control action asks for a fresh code</dd>
              <dt>Last code</dt><dd>{me?.totpAgeS == null ? '—' : Math.round(me.totpAgeS / 60) + ' min ago'}</dd>
              <dt>Typed confirmation</dt><dd>STOP · FLATTEN · the symbol · PAUSE (adapt)</dd>
              <dt>Lockout</dt><dd>5 failed attempts → 15 minutes</dd>
            </dl>
          </div>
        </section>
        <section className="panel c6">
          <div className="ph"><h3>Notifications</h3></div>
          <div className="pb col" style={{ gap: 0 }}>
            <div className="limit"><span><T k="p1p2">P1</T> · push to phone (ntfy)</span><span className="xs muted">CONSOLE_NTFY_URL on the box</span></div>
            <div className="limit"><span>P1 · GitHub issue (live-p1)</span><span className="xs muted">opened by the cycle workflows</span></div>
            <div className="limit"><span>P2 · in the Alerts inbox</span><span className="xs muted">review today</span></div>
          </div>
        </section>
        <section className="panel c6">
          <div className="ph"><h3>Display</h3></div>
          <div className="pb col" style={{ gap: 0 }}>
            <div className="limit"><span>Theme</span><Seg label="Theme" value={theme} onChange={setTheme} items={[{ k: 'light', l: 'Light' }, { k: 'dark', l: 'Dark' }]} /></div>
            <div className="limit"><span>Time zone</span><span className="xs dim">Market times always in ET (New York)</span></div>
            <div className="limit"><span>Explanations</span><span className="xs dim">Hover any dotted-underlined term · full list in Glossary</span></div>
          </div>
        </section>
        {ctx.role === 'owner' && (
          <section className="panel c12">
            <div className="ph"><h3>Server</h3></div>
            <div className="pb col" style={{ gap: 0 }}>
              <div className="limit"><span>Control writes</span><span className={cx('xs', write === 'dry' ? 'warn' : 'muted')}>{write == null ? '—' : write === 'dry' ? <><T k="dryRun">Dry run</T> — nothing is committed (CONSOLE_WRITE=dry)</> : 'CONSOLE_WRITE=' + write}</span></div>
              <div className="limit"><span><T k="dispatch">Workflow dispatch</T></span><span className="xs muted">{cq.data ? (cq.data.dispatch ? 'Configured' : 'Not configured (CONSOLE_GH_TOKEN / CONSOLE_GH_REPO)') : '—'}</span></div>
              <div className="limit"><span><T k="gateway">Broker gateway</T></span><span className="xs muted">{cq.data ? (cq.data.gateway ? 'Configured' : 'Not configured (CONSOLE_GATEWAY_URL)') : '—'}</span></div>
            </div>
          </section>
        )}
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
    ['roadmap', 'Roadmap', 'Phases · D1–D8 · tasks'], ['glossary', 'Glossary', 'Every term in plain words'], ['settings', 'Settings', 'Users · 2FA · display'],
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
