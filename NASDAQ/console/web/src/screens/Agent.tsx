// Agent (M3): parameters against their bounds, regime, the mood journal,
// the adaptation trail and confidence calibration (docs/09 §5.7).

import { useMemo } from 'react';
import { useAgent } from '@/api/client';
import { useConsole, useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { selectAgent } from '@/domain/performance';
import { cx } from '@/lib/format';
import { Chip, PageHeader, Panel, Sk } from '@/components/ui';
import { T } from '@/glossary/Term';

const PCOLS = 'minmax(180px, 1.2fr) 70px minmax(160px, 1fr) 70px';
const CCOLS = '150px 120px 120px 120px 120px 120px 120px';

export function Agent() {
  const ctx = useCtx();
  const { openModal } = useConsole();
  const q = useAgent();
  const fr = selectFresh(ctx);
  const ag = useMemo(() => (q.data ? selectAgent(q.data) : null), [q.data]);
  if (!ag || !q.data) return <div className="page"><PageHeader title="Agent" /><Panel><div className="pb"><Sk h={300} /></div></Panel></div>;
  const a = q.data;
  return (
    <div className="page">
      <PageHeader title={'Agent · ' + a.handle} sub={<>Long-only <T k="momentum">momentum</T> agent · <T k="frozen">frozen</T> at the OOS election{a.freezeCommit ? <> · freeze commit <span className="mono">{a.freezeCommit.slice(0, 7)}</span></> : null}</>}>
        <span className="sp" />
        <Chip cls={ag.adaptCls}>{ag.adaptL}</Chip>
        {ctx.role === 'owner' && <button type="button" className="btn sm" onClick={() => openModal('adapt')}>{a.adaptPaused ? 'Resume adapt()…' : 'Pause adapt()…'}</button>}
      </PageHeader>
      <div className="g12">
        <Panel className="c7" title={<T k="params">Parameters vs bounds</T>} hint={<>marker = current · dotted = value at freeze · <T k="bounds">bounds</T></>} fresh={{ cls: fr.model.cls, l: fr.model.s }}>
          <div className="twrap">
            <div className="dt flush" style={{ minWidth: 520 }}>
              <div className="dt-r dt-h" style={{ gridTemplateColumns: PCOLS }}><span>Parameter</span><span className="r">Value</span><span>Bounds</span><span className="r">At freeze</span></div>
              {ag.params.map((p) => (
                <div key={p.k} className="dt-r" style={{ gridTemplateColumns: PCOLS }}>
                  <span className="col" style={{ gap: 2, minWidth: 0 }}><span className="mono b">{p.k}</span><span className="xs dim wc">{p.d}</span></span><span className={cx('r num b', p.moved && 'info')}>{p.v}</span>
                  <span className="row" style={{ gap: 8 }}><span className="xs muted num">{p.lo}</span>
                    <span className="bar sp" style={{ height: 6, position: 'relative' }}>{p.fz != null && <i className="gauge-ref" style={{ left: p.fz + '%' }} />}{p.pos != null && <i className="gauge-mk" style={{ left: p.pos + '%' }} />}</span>
                    <span className="xs muted num">{p.hi}</span></span>
                  <span className="r num dim">{p.fzv}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
        <Panel className="c5" title={<T k="regime">Regime</T>} hint="what the agent sizes against" fresh={{ cls: fr.model.cls, l: fr.model.s }}>
          <div className="pb col" style={{ gap: 14 }}>
            {!ag.regime.length && <span className="sm muted">Pending — the insights step has not written a file for this session yet.</span>}
            {ag.regime.map((r) => (
              <div key={r.l} className="gauge">
                <div className="gauge-lbl"><span className="dim">{r.l}</span><span className="num b" style={{ color: 'var(--fg-1)' }}>{r.v}</span></div>
                <div className="gauge-t"><i className="gauge-f" style={{ left: r.x + '%', width: r.w + '%' }} /><i className="gauge-ref" style={{ left: r.ref + '%' }} /></div>
                <div className="gauge-lbl"><span>{r.lo}</span><span>{r.note}</span><span>{r.hi}</span></div>
              </div>
            ))}
            <div className="row"><span className="up">Mood</span><Chip>{ag.mood}</Chip><span className="xs muted"><T k="sentiment">sentiment</T> {ag.sent}</span></div>
          </div>
        </Panel>
        <Panel className="c7" title={<T k="journal">Journal · mood &amp; sentiment</T>} hint="−1 … 1 · bands: defensive / choppy / trending">
          <div className="pb col" style={{ gap: 12 }}>
            {ag.pSent ? (
              <div className="chart" style={{ height: 150 }}>
                <div className="plot" style={{ right: 64, top: 4, bottom: 20 }}>
                  <div style={{ position: 'absolute', left: 0, right: 0, top: 0, height: '37.5%', background: 'var(--pos-bg)' }} />
                  <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: '37.5%', background: 'var(--warn-bg)' }} />
                  <span className="ax-y in" style={{ top: '18%' }}>trending</span><span className="ax-y in" style={{ top: '50%' }}>choppy</span><span className="ax-y in" style={{ top: '82%' }}>defensive</span>
                  <div className="hgrid" style={{ top: '50%', borderTopColor: 'var(--line-3)' }} />
                  <svg viewBox="0 0 1000 200" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0 }}><path className="ln sent" d={ag.pSent} /></svg>
                  {ag.xt.map((x) => <span key={x.p} className="ax-x in" style={{ left: x.p + '%' }}>{x.l}</span>)}
                </div>
              </div>
            ) : <span className="sm muted">The journal needs at least two sessions.</span>}
            <div className="col" style={{ gap: 0 }}>
              {ag.journal.slice(0, 8).map((j) => (
                <div key={j.d + j.t} className="row" style={{ alignItems: 'flex-start', gap: 12, padding: '9px 0', borderTop: '1px solid var(--line-1)' }}>
                  <span className="num xs muted" style={{ width: 84, flex: 'none', paddingTop: 2 }}>{j.d}</span><Chip style={{ flex: 'none' }}>{j.m} · {j.s}</Chip><span className="sm dim" style={{ lineHeight: 1.5 }}>{j.t}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
        <Panel className="c5" title={<T k="adapt">Adaptation trail</T>} hint={'adapt() every ' + a.adaptEvery + ' sessions'}>
          <div className="pb col" style={{ gap: 0 }}>
            {!ag.trail.length && <span className="sm muted">No adaptations yet.</span>}
            {ag.trail.map((t, i) => (
              <div key={i} className="row" style={{ alignItems: 'flex-start', gap: 12, padding: '9px 0', borderBottom: '1px solid var(--line-1)' }}>
                <span className={cx('mk', t.cls)} style={{ position: 'static', transform: 'none', paddingTop: 2 }}>{t.g}</span>
                <div className="col gap4" style={{ minWidth: 0 }}><span className="b sm">{t.d}</span><span className="xs dim">{t.t}</span>{t.diff && <span className="mono xs muted wc">{t.diff}</span>}</div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel className="c12" title={<T k="calibration">Confidence calibration</T>} hint="does the band mean something? · model conviction, not a forecast" footer={<span className="muted">{ag.calNote}</span>}>
          <div className="twrap">
            <div className="dt flush">
              <div className="dt-r dt-h" style={{ gridTemplateColumns: CCOLS }}><span>Band</span><span className="r">OOS position-days</span><span className="r">OOS trade won</span><span className="r">OOS 20-session return</span><span className="r">Live round trips</span><span className="r">Live hit rate</span><span className="r">Live avg return</span></div>
              {ag.cal.map((c) => (
                <div key={c.band} className="dt-r" style={{ gridTemplateColumns: CCOLS }}>
                  <span><span className={cx('conf', c.band)}><span className="conf-b" style={{ width: 'auto' }}>{c.l}</span></span></span>
                  <span className="r num">{c.oosN}</span><span className="r num b">{c.oosHit}</span><span className={cx('r num', c.oosRetCls)}>{c.oosRet}</span>
                  <span className="r num">{c.n}</span><span className="r num">{c.hit}</span><span className={cx('r num', c.retCls)}>{c.ret}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
