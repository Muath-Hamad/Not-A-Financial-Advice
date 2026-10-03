// The executive desk (M1, docs/08 §7): trading state, holding overrides,
// exclusions, manual orders, risk limits, adapt(), re-runs. Every button
// opens the same 4-step confirm; nothing changes without it.

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { postJson, useControls } from '@/api/client';
import { useConsole, useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { selectControls } from '@/domain/controls';
import { sn } from '@/domain/performance';
import type { ControlAction } from '@/domain/actions';
import { cx } from '@/lib/format';
import { wdLabel } from '@/lib/dates';
import { Icon } from '@/components/icons';
import { Chip, Conf, Fresh, Note, PageHeader, Panel, Shar, Sk } from '@/components/ui';
import { Gloss, T } from '@/glossary/Term';

export function Controls() {
  const ctx = useCtx();
  const { positions, openModal, openDrawer, setPreflightOpen, me, showToast } = useConsole();
  const cq = useControls(ctx.role === 'owner');
  const qc = useQueryClient();
  const [cause, setCause] = useState('');
  const [capOn, setCapOn] = useState<boolean | null>(null);
  const [cap, setCap] = useState<number | null>(null);
  const [step, setStep] = useState('Cycle A');
  const fr = selectFresh(ctx);
  if (ctx.role !== 'owner') {
    return <div className="page"><PageHeader title="Controls" /><Note tone="warn">Read-only viewer: Controls are owner-only.</Note></div>;
  }
  if (!cq.data) return <div className="page"><PageHeader title="Controls" /><Panel><div className="pb"><Sk h={260} /></div></Panel></div>;
  const ct = selectControls(ctx, cq.data, positions);
  const go = (a: ControlAction, params: Record<string, unknown> = {}) => (a === 'resume' ? setPreflightOpen(true) : openModal(a, params));
  const capEnabled = capOn ?? ct.grossCap != null;
  const capValue = cap ?? ct.grossCap ?? 90;
  const capTarget = capEnabled ? capValue : null;
  const causeN = cause.trim().length;
  const sync = async () => {
    const r = await postJson<{ changed: boolean }>('/api/sync');
    qc.invalidateQueries();
    showToast(r.changed ? 'Ledger synced · new commits indexed' : 'Ledger synced · no new commits');
  };
  return (
    <div className="page ctl-page">
      <PageHeader title="Controls" sub="Executive desk · every action runs impact preview → reason → 2FA → result, writes controls.json and commits to the ledger">
        <span className="sp" />
        <Chip><Icon name="lock" className="s14" />{me?.auth ? 'Owner · 2FA on every action' : 'Owner · authentication off (dev)'}</Chip>
      </PageHeader>
      {ct.write === 'dry' && <Note tone="warn">Dry run (CONSOLE_WRITE=dry): actions are validated and logged in the console, but nothing is committed to the ledger. Set CONSOLE_WRITE=git or github on the box.</Note>}
      {ct.err && <Note tone="danger">Broker unreachable — immediate broker commands (cancel all, flatten) will fail and report “Not applied”. Control-file changes still commit and are read by the next cycle.</Note>}
      {ct.stale && <Note tone="warn">Cycle A is failing, so the next submit has nothing to send. Controls still commit and are read by the next successful cycle.</Note>}

      <div className="g12">
        <Panel className="c8" title={<T k="killSwitch">Trading state</T>} fresh={fr.ledger}>
          <div className="pb col" style={{ gap: 18 }}>
            <div className="ctl-state">
              <span className={cx('pill static', { running: 'green', paused: 'amber', held: 'amber pulse', halted: 'red', stopped: 'red' }[ctx.trading])} style={{ height: 36, fontSize: 13, padding: '0 16px' }}><span className="pd" />{ct.big}</span>
              <div className="col gap4"><span className="sm">{ct.since}</span><span className="xs muted"><Gloss text={ct.reads} /></span></div>
            </div>
            <div className="ctl-acts">
              {[ct.b1, ct.b2, ct.b3].map((b) => (
                <div key={b.l} className="ctl-act">
                  <button type="button" className={cx('btn lg', b.cls)} onClick={() => go(b.action)} disabled={b.dis}>{b.l}</button>
                  <span className="eff">Effective: <b>{b.eff}</b></span><span className="xs muted"><Gloss text={b.sub} /></span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
        <Panel className="c4" title="Pending control changes" extra={<span className="cnt">{ct.pending.length}</span>} hint="committed, not yet read by a cycle">
          {!ct.pending.length && <div className="pb sm muted">Nothing pending. Every committed control has been read by a cycle.</div>}
          <div className="att">
            {ct.pending.map((p) => (
              <div key={p.sha} className="att-i" style={{ alignItems: 'flex-start' }}>
                <span className="dot info" style={{ marginTop: 6 }} />
                <div className="att-t"><span className="b"><Gloss text={p.what} /></span><span className="s">Effective: {p.eff}</span><span className="s"><span className="mono">{p.sha}</span> · committed {p.when}</span></div>
              </div>
            ))}
          </div>
        </Panel>

        {ct.held && (
          <section className="panel c12" style={{ borderColor: 'var(--warn-line)' }}>
            <div className="ph"><h3><T k="approval">Night release</T></h3><span className="pill static amber pulse"><span className="pd" />Held · approval needed</span></div>
            <div className="pb row wrap" style={{ gap: 20 }}>
              <span className="sm dim sp">Soft holds only (approval mode, a portfolio guardrail). Release runs the submit with --approved; the window closes at 09:28 ET.</span>
              <button type="button" className="btn lg primary" onClick={() => go('release')}>Release tonight’s submission…</button>
            </div>
          </section>
        )}

        {ct.halted && (
          <section className="panel c12" style={{ borderColor: 'var(--danger-line)' }}>
            <div className="ph"><h3><T k="halt">Reconciliation halt</T></h3><span className="pill static red"><span className="pd" />Halted</span><Fresh cls="red" l={'ledger/halt.json' + (ct.haltSince ? ' · ' + wdLabel(ct.haltSince) : '')} /></div>
            <div className="pb g2" style={{ gap: 20 }}>
              <div className="col" style={{ gap: 8 }}>
                <span className="up">Share-for-share diff · positions before submission + fills = positions now</span>
                <div className="twrap"><div className="dt flush dense">
                  <div className="dt-r dt-h" style={{ gridTemplateColumns: '1fr 90px 90px 80px' }}><span>Symbol</span><span className="r">Expected</span><span className="r">Actual</span><span className="r">Diff</span></div>
                  {ct.haltDiffs.map((d) => (
                    <div key={d.symbol} className="dt-r" style={{ gridTemplateColumns: '1fr 90px 90px 80px' }}><span className="sym">{d.symbol}</span><span className="r num">{d.expected}</span><span className="r num acct">{d.actual}</span><span className="r"><Chip cls="danger">{d.actual - d.expected > 0 ? '+' : '−'}{Math.abs(d.actual - d.expected)}</Chip></span></div>
                  ))}
                </div></div>
              </div>
              <div className="col" style={{ gap: 8 }}>
                <label className="lbl" htmlFor="haltcause" style={{ margin: 0 }}>Cause (required, written into halt.json)</label>
                <textarea id="haltcause" className="ta" value={cause} onChange={(e) => setCause(e.target.value)} placeholder="e.g. corporate action: the broker delivered one share late; verified in account activities" />
                <div className="row"><span className={cx('xs', causeN >= 10 ? 'pos' : 'muted')}>{causeN >= 10 ? causeN + ' characters ✓' : causeN + ' / 10 characters minimum'}</span><span className="sp" />
                  <button type="button" className="btn primary" disabled={causeN < 10} onClick={() => go('clear_halt', { cause })}>Clear halt…</button></div>
              </div>
            </div>
          </section>
        )}

        <Panel className="c8" title="Holding overrides" hint="effective at the next 19:15 ET submit" fresh={{ cls: fr.model.cls, l: fr.model.s }}>
          <div className="twrap wide-only">
            <div className="dt flush">
              <div className="dt-r dt-h" style={{ gridTemplateColumns: '150px 80px 130px 150px 70px 90px 120px minmax(170px, 1fr)' }}>
                <span>Symbol</span><span className="r"><T k="weight">Weight</T></span><span><T k="confidence">Confidence</T></span><span><T k="shariaGrade">Sharia</T></span><span><T k="locked">Lock</T></span><span /><span /><span>Status</span>
              </div>
              {ct.ovr.map((o) => (
                <div key={o.s} className="dt-r" style={{ gridTemplateColumns: '150px 80px 130px 150px 70px 90px 120px minmax(170px, 1fr)' }}>
                  <span><button type="button" className="linkbtn" onClick={() => openDrawer(o.s)}><span className="sym">{o.s}</span></button><span className="symname">{o.n}</span></span>
                  <span className="r num">{o.w}</span>
                  <span><Conf c={o.c} band={o.band} bandL={o.bandL} bar={false} /></span>
                  <span><Shar g={o.g} gCls={o.gCls} stat={o.stat} /></span>
                  <span><button type="button" className={cx('switch', o.locked && 'on amber')} onClick={() => go(o.locked ? 'unlock' : 'lock', { symbol: o.s })} aria-label={(o.locked ? 'Unlock ' : 'Lock ') + o.s} aria-pressed={o.locked} disabled={o.forced} /></span>
                  <span><button type="button" className="btn sm" onClick={() => go('trim', { symbol: o.s, pct: 50 })} disabled={o.forced}>Trim…</button></span>
                  <span><button type="button" className="btn sm danger-o" onClick={() => go('force_exit', { symbol: o.s })} disabled={o.forced}>Force exit…</button></span>
                  <span className={cx('xs', o.stCls)}>{o.status}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="narrow-only">
            {ct.ovr.map((o) => (
              <div key={o.s} className="mcard">
                <span className="mcard-h"><span className="sym">{o.s}</span><span className="num xs muted">{o.w}</span><span className={cx('grade', o.gCls)}>{o.g}</span><span className="sp" /><span className={cx('xs', o.stCls)}>{o.status}</span></span>
                <span className="row" style={{ gap: 8 }}>
                  <span className="row gap4 sm" style={{ flex: 1 }}><button type="button" className={cx('switch', o.locked && 'on amber')} onClick={() => go(o.locked ? 'unlock' : 'lock', { symbol: o.s })} aria-label={'Lock ' + o.s} disabled={o.forced} />Lock</span>
                  <button type="button" className="btn" style={{ height: 44, flex: 1 }} onClick={() => go('trim', { symbol: o.s, pct: 50 })} disabled={o.forced}>Trim…</button>
                  <button type="button" className="btn danger-o" style={{ height: 44, flex: 1 }} onClick={() => go('force_exit', { symbol: o.s })} disabled={o.forced}>Force exit…</button>
                </span>
              </div>
            ))}
          </div>
          <div className="pb col" style={{ gap: 14, borderTop: '1px solid var(--line-1)' }}>
            <div className="col" style={{ gap: 6 }}>
              <span className="up"><T k="excluded">Excluded symbols</T> · block buys; held names get a forced exit</span>
              <div className="row wrap" style={{ gap: 6 }}>
                {ct.excluded.map((s) => (
                  <span key={s} className={cx('chip', positions.some((h) => h.symbol === s) && 'danger')}>{s}<button type="button" className="x" onClick={() => go('unexclude', { symbol: s })} aria-label={'Remove ' + s + ' from exclusions'}>×</button></span>
                ))}
                {!ct.excluded.length && <span className="sm muted">None</span>}
              </div>
            </div>
            <div className="row wrap" style={{ gap: 24 }}>
              <div className="col" style={{ gap: 6 }}><span className="up">Locked</span><span className={cx('sm', ct.locked.length ? 'warn b' : 'muted')}>{ct.locked.join(', ') || 'None'}</span></div>
              <div className="col sp" style={{ gap: 6 }}><span className="up">Manual order queue</span>
                {!ct.manual.length && <span className="sm muted">Empty</span>}
                {ct.manual.map((m) => (
                  <div key={m.id} className="row sm" style={{ gap: 8 }}><span className={cx('side', m.side)}>{m.side.toUpperCase()}</span><span className="sym">{m.symbol}</span><span className="num">{m.qty ?? Math.round((m.fraction ?? 0) * 100) + '%'} sh</span>
                    <span className="xs muted">expires {wdLabel(m.expires)} 09:28 ET</span><button type="button" className="btn sm ghost" onClick={() => go('cancel_manual', { id: m.id, symbol: m.symbol })}>Cancel…</button></div>
                ))}
              </div>
            </div>
          </div>
        </Panel>

        <div className="col c4" style={{ gap: 16 }}>
          <Panel title="Risk limits">
            <div className="pb col" style={{ gap: 10 }}>
              <div className="row"><span className="b sm"><T k="grossCap">Gross exposure cap</T></span><span className="sp" /><span className="num b">{capEnabled ? capValue + '%' : 'Off'}</span>
                <button type="button" className={cx('switch', capEnabled && 'on')} onClick={() => setCapOn(!capEnabled)} aria-label="Gross cap on or off" aria-pressed={capEnabled} /></div>
              <input type="range" className="range" min={50} max={100} step={5} value={capValue} onChange={(e) => setCap(Number(e.target.value))} disabled={!capEnabled} aria-label="Gross cap percent" />
              <div className="row"><span className="xs muted">Applied: {ct.grossCap == null ? 'off' : ct.grossCap + '%'} · <T k="exposure">exposure</T> now {ct.exposure}%</span><span className="sp" />
                <button type="button" className="btn sm" onClick={() => go('gross', { cap: capTarget })} disabled={capTarget === ct.grossCap}>Apply…</button></div>
              <span className="eff">Effective: <b>the next Cycle A</b></span>
              <hr className="hr" />
              <span className="up"><T k="guardrails">Hard guardrails</T> · read-only</span>
              <div className="col" style={{ gap: 0 }}>
                <div className="limit"><span><T k="posCap">Max position weight</T></span><span className="num"><b>{pct(ct.limits.MAX_POS_WEIGHT)}</b></span></div>
                <div className="limit"><span><T k="turnover">Daily turnover</T></span><span className="num"><b>{pct(ct.limits.MAX_DAILY_TURNOVER)}</b></span></div>
                <div className="limit"><span><T k="advCap">ADV cap per order</T></span><span className="num"><b>{pct(ct.limits.ADV_CAP)}</b></span></div>
                <div className="limit"><span><T k="killLine">Drawdown kill</T></span><span className="num"><b className="danger">{pct(ct.limits.KILL_DD_LIMIT)}</b> <span className="xs muted">now {sn(ct.drawdown, 1)}%</span></span></div>
              </div>
            </div>
          </Panel>
          <Panel title={<T k="adapt">Agent learning</T>}>
            <div className="pb col" style={{ gap: 10 }}>
              <div className="row"><div className="col gap4 sp"><span className="b sm">Pause adapt()</span>
                <span className="xs muted">{ct.adaptPaused ? 'Paused' + (ct.adaptSince ? ' from ' + wdLabel(ct.adaptSince) : '') + ' — parameters frozen' : 'Learning on · adapt() every 63 sessions'}</span></div>
                <button type="button" className={cx('switch', ct.adaptPaused && 'on amber')} onClick={() => go('adapt')} aria-label="Pause adapt" aria-pressed={ct.adaptPaused} /></div>
              <Note tone="warn">Fidelity: pausing changes the twin path and ends comparability with the frozen OOS record.</Note>
              <span className="eff">Effective: <b>the next Cycle A</b></span>
            </div>
          </Panel>
          <Panel title="Maintenance">
            <div className="pb col" style={{ gap: 10 }}>
              <div className="row wrap" style={{ gap: 8 }}>
                <select className="sel" value={step} onChange={(e) => setStep(e.target.value)} aria-label="Step to re-run"><option>Cycle A</option><option>Submit</option><option>Cycle B</option></select>
                <button type="button" className="btn" onClick={() => go('rerun', { step })} disabled={!ct.dispatch}><Icon name="refresh" className="s14" />Re-run…</button>
              </div>
              <span className="xs muted">{ct.dispatch ? 'Steps are idempotent: a re-run for the same date never duplicates orders. A missed submit can run until 09:28 ET.' : 'Workflow dispatch is not configured (CONSOLE_GH_TOKEN / CONSOLE_GH_REPO).'}</span>
              <hr className="hr" />
              <div className="row"><span className="sm">Ledger <T k="indexer">indexer</T></span><span className="sp" /><button type="button" className="btn sm" onClick={sync}>Sync now</button></div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

const pct = (v: number | null | undefined) => (v == null ? '—' : Math.round(v * 100) + '%');
