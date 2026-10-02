// App shell: top bar, banners, nav / rail, phone tab bar, the routed page,
// the holding drawer, toast and ⌘K palette. Breakpoints are container
// queries on .app (nafa.css), so the shell responds to its own width.

import { useEffect, useMemo, type ReactNode } from 'react';
import { Outlet } from 'react-router-dom';
import { cx } from '@/lib/format';
import { selectBanners, selectEmpty, selectNav, selectTop, SYSTEM_SCREENS, MORE_SCREENS } from '@/domain/chrome';
import type { Screen } from '@/domain/actions';
import { Icon, ToneIcon, type IconName } from '@/components/icons';
import { Empty, PageHeader, Sk } from '@/components/ui';
import { useConsole, useCtx } from './console';
import { HoldingDrawer } from '@/screens/HoldingDrawer';
import { Palette } from './Palette';

export function Shell({ height = '100vh', overlay }: { height?: string; overlay?: ReactNode }) {
  const { ctx, theme, apiDown, toast, palette, setPalette, drawer } = useConsole();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPalette(!palette);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [palette, setPalette]);

  return (
    <div className={cx('nafa app', ctx?.env === 'live' && 'is-live')} data-theme={theme} style={{ height, minHeight: height === '100vh' ? 640 : 0 }}>
      {ctx ? <TopBar /> : <BootTopBar />}
      <div className="banners">
        {ctx && <NarrowTonight />}
        {apiDown && (
          <div className="banner red" role="status">
            <ToneIcon tone="red" className="bi" />
            <div className="bt"><b>Console API unreachable.</b> The read model could not be loaded; trading is unaffected — the harness never depends on the console.</div>
          </div>
        )}
        {ctx && <Banners />}
      </div>
      <div className="body">
        {ctx ? <Nav /> : <nav className="nav" aria-label="Primary" />}
        <main className="main">
          <Page />
        </main>
      </div>
      {ctx && <TabBar />}
      {ctx && drawer && <HoldingDrawer sym={drawer} />}
      {palette && ctx && <Palette />}
      {overlay}
      {toast && <div className="toast" role="status"><Icon name="check" /><span>{toast}</span></div>}
    </div>
  );
}

function Page() {
  const { ctx, screen, apiDown } = useConsole();
  if (!ctx) {
    if (apiDown) return <div className="page"><Empty icon="octagon" title="No data">The console API did not answer. Check the nafa-console container and the indexer on the Health endpoint (/healthz).</Empty></div>;
    return <LoadingPage />;
  }
  if (ctx.data === 'loading') return <LoadingPage />;
  if (ctx.data === 'empty' && !SYSTEM_SCREENS.includes(screen)) return <EmptyPage screen={screen} />;
  return <Outlet />;
}

/* ───────── top bar ───────── */

function BootTopBar() {
  return (
    <header className="top">
      <Brand />
      <span className="top-sp" />
      <span className="sync amber"><span className="d" /><span>Connecting…</span></span>
    </header>
  );
}

function Brand() {
  return <div className="brand"><span className="brand-mark">N</span><span className="brand-name">NAFA <span>Console</span></span></div>;
}

function TopBar() {
  const { alerts, theme, setTheme, setPalette, go } = useConsole();
  const ctx = useCtx();
  const top = useMemo(() => selectTop(ctx, alerts), [ctx, alerts]);
  const owner = ctx.role === 'owner';
  return (
    <header className="top">
      <Brand />
      <span className={cx('env', top.envCls)} title={top.envT}>{top.envL}</span>
      <button type="button" className={cx('pill', top.pillCls)} onClick={() => go(owner ? 'controls' : 'health')} title="Trading state — open Controls">
        <span className="pd" /><span className="wide-only">{top.pillL}</span><span className="narrow-only">{top.pillS}</span>
      </button>
      <div className="tl" role="group" aria-label="Tonight's schedule">
        {top.tl.map((t) => (
          <button key={t.l} type="button" className={cx('tl-step', t.cls)} onClick={() => go('health')} title={t.title}>
            <span className="g">{t.g}</span><span>{t.l}</span><span className="t tl-x">{t.time}</span><span className="tl-cd">{t.cd}</span>
          </button>
        ))}
      </div>
      <span className="top-sp" />
      <span className={cx('sync', top.syncCls)} title={top.syncT}><span className="d" /><span>{top.sync1}</span><span className="st">· {top.sync2}</span></span>
      <button type="button" className="top-btn" onClick={() => setPalette(true)} aria-label="Command palette"><Icon name="search" /><span className="kbd">⌘K</span></button>
      <button type="button" className="top-btn" onClick={() => go('alerts')} aria-label={top.bellT} title={top.bellT}>
        <Icon name="bell" /><span className={cx('bell-n', top.p1Cls)}>{top.p1}</span><span className={cx('bell-n', top.p2Cls)}>{top.p2}</span>
      </button>
      <button type="button" className="top-btn wide-only" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label="Toggle light or dark theme" title="Theme">
        <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
      </button>
      <span className="avatar wide-only" title={owner ? 'M · Owner' : 'Sharia reviewer · read-only viewer'}>{owner ? 'M' : 'SR'}</span>
    </header>
  );
}

function NarrowTonight() {
  const { alerts } = useConsole();
  const ctx = useCtx();
  const top = selectTop(ctx, alerts);
  return (
    <div className="narrow-only">
      <div className="row" style={{ padding: '7px 16px', borderBottom: '1px solid var(--line-1)', background: 'var(--bg-1)', fontSize: 11.5, gap: 10, whiteSpace: 'nowrap', overflow: 'hidden' }}>
        <span className="muted">Tonight</span>
        {top.tl.map((t) => <span key={t.l} className={t.mcls}>{t.g} {t.ms}</span>)}
        <span className="sp" /><span className="tl-cd">{top.cd}</span>
      </div>
    </div>
  );
}

function Banners() {
  const { dispatch } = useConsole();
  const ctx = useCtx();
  return (
    <>
      {selectBanners(ctx).map((b) => (
        <div key={b.title} className={cx('banner', b.tone)} role="status">
          <ToneIcon tone={b.tone} className="bi" />
          <div className="bt"><b>{b.title}</b> {b.text}</div>
          <div className="ba">{b.acts.map((x) => <button key={x.l} type="button" className={cx('btn sm', x.cls)} onClick={() => dispatch(x.intent)}>{x.l}</button>)}</div>
        </div>
      ))}
    </>
  );
}

/* ───────── nav, rail and tab bar ───────── */

function NavItem({ k, icon, label, badge, badgeCls, ctl }: { k: Screen; icon: IconName; label: string; badge?: string; badgeCls?: string; ctl?: boolean }) {
  const { screen, go } = useConsole();
  return (
    <button type="button" className={cx('nav-item', ctl && 'ctl', screen === k && 'on')} onClick={() => go(k)} title={label} aria-current={screen === k ? 'page' : undefined}>
      <span className="nav-ico"><Icon name={icon} /></span><span className="nav-label">{label}</span>
      {badge !== undefined && <span className={cx('nav-badge', badgeCls)}>{badge}</span>}
    </button>
  );
}

function Nav() {
  const { positions, intents, alerts } = useConsole();
  const ctx = useCtx();
  const n = selectNav(ctx, positions, intents, alerts);
  return (
    <nav className="nav" aria-label="Primary">
      <div className="nav-sec">Monitor</div>
      <NavItem k="overview" icon="overview" label="Overview" />
      <NavItem k="holdings" icon="holdings" label="Holdings" badge={n.bHold} />
      <NavItem k="orders" icon="orders" label="Orders" badge={n.bOrd} />
      <NavItem k="performance" icon="performance" label="Performance" />
      <NavItem k="compliance" icon="compliance" label="Compliance" badge={n.bComp} badgeCls={n.bCompCls} />
      {ctx.role === 'owner' && (
        <>
          <div className="nav-sec">Act</div>
          <NavItem k="controls" icon="controls" label="Controls" badge={n.bCtl} badgeCls={n.bCtlCls} ctl />
        </>
      )}
      <div className="nav-sec">System</div>
      <NavItem k="agent" icon="agent" label="Agent" />
      <NavItem k="health" icon="health" label="Health" badge={n.bHealth} badgeCls={n.bHealthCls} />
      <NavItem k="alerts" icon="bell" label="Alerts" badge={n.bAl} badgeCls={n.bAlCls} />
      <NavItem k="audit" icon="audit" label="Audit log" />
      <NavItem k="roadmap" icon="roadmap" label="Roadmap" />
      <div className="nav-foot">
        <NavItem k="settings" icon="settings" label="Settings" />
      </div>
    </nav>
  );
}

function TabBar() {
  const { screen, go, positions, intents, alerts } = useConsole();
  const ctx = useCtx();
  const n = selectNav(ctx, positions, intents, alerts);
  const Tb = ({ k, icon, label, ctl, children }: { k: Screen; icon: IconName; label: string; ctl?: boolean; children?: ReactNode }) => {
    const on = k === 'more' ? MORE_SCREENS.includes(screen) : screen === k;
    return (
      <button type="button" className={cx('tb-btn', ctl && 'ctl', on && 'on')} onClick={() => go(k)} aria-current={on ? 'page' : undefined}>
        <Icon name={icon} />{label}{children}
      </button>
    );
  };
  return (
    <nav className="tabbar" aria-label="Primary">
      <Tb k="overview" icon="overview" label="Overview" />
      <Tb k="holdings" icon="holdings" label="Holdings" />
      <Tb k="orders" icon="orders" label="Orders" />
      {ctx.role === 'owner' && <Tb k="controls" icon="controls" label="Controls" ctl>{n.ctlAlert && <span className="tb-n">!</span>}</Tb>}
      <Tb k="more" icon="more" label="More">{n.moreAlert && <span className="tb-n">{n.moreN}</span>}</Tb>
    </nav>
  );
}

/* ───────── loading and empty pages ───────── */

function LoadingPage() {
  const six = [1, 2, 3, 4, 5, 6];
  return (
    <div className="page" aria-busy="true">
      <div className="page-h"><div className="col gap4"><Sk w={160} h={22} /><Sk w={320} h={12} /></div></div>
      <div className="kpis">
        {six.map((k) => (
          <div key={k} className="kpi"><Sk w="55%" h={10} /><Sk w="80%" h={22} style={{ marginTop: 6 }} /><Sk w="45%" h={10} style={{ marginTop: 4 }} /><Sk w="100%" h={22} style={{ marginTop: 6 }} /></div>
        ))}
      </div>
      <div className="g12">
        <div className="panel c8"><div className="ph"><Sk w={120} h={12} /><span className="fresh amber">Loading ledger…</span></div><div className="pb"><Sk h={250} /></div></div>
        <div className="panel c4"><div className="ph"><Sk w={90} h={12} /></div><div className="pb col gap12">{[1, 2, 3, 4, 5].map((k) => <div key={k} className="row"><Sk w={22} h={22} /><Sk h={30} style={{ flex: 1 }} /></div>)}</div></div>
        <div className="panel c12"><div className="ph"><Sk w={140} h={12} /></div><div className="pb col gap12">{six.map((k) => <Sk key={k} h={22} />)}</div></div>
      </div>
    </div>
  );
}

function EmptyPage({ screen }: { screen: Screen }) {
  const { go } = useConsole();
  const em = selectEmpty(screen);
  const kpis: [string, string, string, boolean][] = [
    ['Equity', '$100,000.00', 'all cash · nothing invested', false],
    ['Today’s P&L', '$0.00', 'no session yet', true],
    ['Drawdown', '0.0%', 'kill line −25%', true],
    ['Exposure', '0.0%', 'cash $100,000.00', true],
    ['Positions', '0 / 15', 'first entries after Cycle A', true],
    ['Orders for next open', '—', 'ledgered at 17:05 ET', true],
  ];
  return (
    <div className="page">
      <PageHeader title={em.title} sub="Cold start — the twin and the account both begin in cash on the same session (decision D5)" />
      <div className="kpis">
        {kpis.map(([l, v, s, m]) => <div key={l} className="kpi"><div className="kpi-l">{l}</div><div className={cx('kpi-v', m && 'muted')}>{v}</div><div className="kpi-s">{s}</div></div>)}
      </div>
      <section className="panel">
        <Empty title={em.h} actions={<><button type="button" className="btn" onClick={() => go('roadmap')}>View roadmap</button><button type="button" className="btn ghost" onClick={() => go('health')}>Scheduled steps</button></>}>{em.p}</Empty>
      </section>
    </div>
  );
}
