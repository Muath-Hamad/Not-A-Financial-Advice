import { useState } from 'react';
import { useHealth } from '@/api/client';
import { useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { selectHealth } from '@/domain/health';
import { cx } from '@/lib/format';
import { Chip, Fresh, PageHeader, Panel, Sk } from '@/components/ui';
import { Gloss, T } from '@/glossary/Term';

export function Health() {
  const ctx = useCtx();
  const hq = useHealth();
  const [cell, setCell] = useState<string | null>(null);
  const fr = selectFresh(ctx);
  if (!hq.data) return <div className="page"><PageHeader title="Health" /><Panel><div className="pb"><Sk h={260} /></div></Panel></div>;
  const he = selectHealth(hq.data, cell);
  return (
    <div className="page">
      <PageHeader title="Health" sub={<Gloss text={he.sub} />}><span className="sp" /><span className={cx('pill static', he.pillCls)}><span className="pd" />{he.pill}</span></PageHeader>
      <div className="g12">
        <section className="panel c8">
          <div className="ph"><h3>Cycle timeline</h3><span className="hint">last 14 <T k="session">sessions</T> × <T k="cycleA">Cycle A</T> · <T k="submit">Submit</T> · <T k="cycleB">Cycle B</T> — click a cell for its record</span><Fresh cls={fr.ledger.cls} l={fr.ledger.l} /></div>
          <div className="pb col" style={{ gap: 10 }}>
            <div className="twrap">
              <div className="col gap4" style={{ minWidth: 620 }}>
                <div className="row" style={{ gap: 8 }}>
                  <span style={{ width: 14, flex: 'none' }} />
                  <div className="cyc sp">{he.days.map((d) => <span key={d.w + d.l} className="c num" style={{ fontSize: 10, color: 'var(--fg-3)', lineHeight: 1.2 }}>{d.w}<br />{d.l}</span>)}</div>
                </div>
                {he.rows.map((r) => (
                  <div key={r.k} className="row" style={{ gap: 8 }}>
                    <span className="mono xs muted" style={{ width: 14, flex: 'none' }}>{r.k}</span>
                    <div className="cyc sp">{r.c.map((c) => <button key={c.id} type="button" className={cx('cyc-c', c.cls)} onClick={() => setCell(c.id)} title={c.t} aria-label={c.t}>{c.g}</button>)}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="legend">
              <span><span className="cyc-c ok" style={{ width: 16, height: 14, display: 'inline-block' }} />ok</span>
              <span><span className="cyc-c fail" style={{ width: 16, height: 14, display: 'inline-block' }} />failed / data gate</span>
              <span><span className="cyc-c held" style={{ width: 16, height: 14, display: 'inline-block' }} />held</span>
              <span><span className="cyc-c skip" style={{ width: 16, height: 14, display: 'inline-block' }} />skipped / not yet</span>
            </div>
            <div className="col" style={{ gap: 6 }}><span className="up">{he.selT}</span><pre className="code" style={{ margin: 0, maxHeight: 200 }}>{he.selJ}</pre></div>
          </div>
        </section>

        <Panel className="c4" title={<T k="ghostGate">Ghost gate</T>} hint={<>10 consecutive <T k="determinism">deterministic</T> sessions</>}>
          <div className="pb col" style={{ gap: 12 }}>
            <div className="row"><span className="kpi-v num">{he.gate.streak}<span className="muted" style={{ fontSize: 14 }}> / {he.gate.target}</span></span><span className="sp" /><Chip cls={he.gate.cls}>{he.gate.l}</Chip></div>
            <div className="slots" style={{ height: 10 }}>{he.gate.slots.map((f, i) => <span key={i} className={f ? 'f' : ''} />)}</div>
            <span className="xs muted">{he.gate.note}</span>
            <hr className="hr" />
            <span className="up"><T k="determinism">Hash history</T></span>
            <div className="col" style={{ gap: 6 }}>
              {he.gate.hashes.map((h) => (
                <div key={h.date} className="row xs" style={{ gap: 8 }}><span className="num muted" style={{ width: 70, flex: 'none' }}>{h.date}</span><span className="mono sp" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.hash}</span><span className={h.cls}>{h.result}</span></div>
              ))}
            </div>
            <hr className="hr" />
            <span className="up"><T k="determinism">Determinism · last sha256</T></span>
            <span className="hash">{he.gate.sha}</span>
            <span className="xs pos">{he.gate.replay}</span>
          </div>
        </Panel>

        <section className="panel c6">
          <div className="ph"><h3><T k="dataGate">Data gate</T></h3><span className="hint">{he.dg.when}</span><Fresh cls={he.dg.cls} l={he.dg.l} /></div>
          <div className="pb col" style={{ gap: 0 }}>
            {he.dg.checks.map((c) => (
              <div key={c.l} className="limit"><span className="row gap4"><span className={cx(c.cls, 'b')} style={{ width: 16 }}>{c.g}</span><Gloss text={c.l} /></span><span className="num"><b className={c.cls}>{c.v}</b> <span className="xs muted">{c.min}</span></span></div>
            ))}
          </div>
          {he.dg.missing && (
            <div className="pb col" style={{ gap: 8, borderTop: '1px solid var(--line-1)' }}>
              <span className="up">{he.dg.missing.title}</span>
              <div className="row wrap" style={{ gap: 5 }}>{he.dg.missing.sample.map((s) => <Chip key={s} cls="mono">{s}</Chip>)}<Chip cls="out">{he.dg.missing.more}</Chip></div>
              <span className="xs muted">{he.dg.missing.note}</span>
            </div>
          )}
        </section>

        <Panel className="c6" title="Broker" fresh={fr.broker}>
          <div className="pb"><dl className="kv" style={{ margin: 0 }}>{he.broker.map((b) => <Pair key={b.k} k={b.k} v={b.v} cls={b.cls} />)}</dl></div>
        </Panel>

        <Panel className="c8" title={<T k="heartbeat">Heartbeats</T>} hint={<>external check per scheduled step · a <T k="deadman">dead-man</T> inside the box cannot see its own death</>}>
          <div className="twrap">
            <div className="dt flush dense">
              <div className="dt-r dt-h" style={{ gridTemplateColumns: 'minmax(180px, 1fr) 120px 150px 120px 120px' }}><span>Step</span><span>Expected (ET)</span><span>Last ping</span><span>Duration</span><span>Status</span></div>
              {he.hb.map((h) => (
                <div key={h.step} className="dt-r" style={{ gridTemplateColumns: 'minmax(180px, 1fr) 120px 150px 120px 120px' }}>
                  <span className="mono">{h.step}</span><span className="num">{h.expected}</span><span className="num dim">{h.last}</span><span className="num dim">{h.duration}</span>
                  <span className="lc"><span className={cx('dot', h.dot)} /><span className={h.cls}>{h.status}</span></span>
                </div>
              ))}
            </div>
          </div>
        </Panel>

        <Panel className="c4" title={<T k="indexer">Indexer</T>} fresh={{ cls: he.ix.cls, l: he.ix.label }}>
          <div className="pb">
            <dl className="kv" style={{ margin: 0 }}>
              <dt>Last <T k="commit">commit</T> indexed</dt><dd className="mono">{he.ix.commit}</dd>
              <dt>Message</dt><dd className="xs dim">{he.ix.message}</dd>
              <dt>Lag</dt><dd>{he.ix.lag}</dd>
              <dt>Errors (24 h)</dt><dd>{he.ix.errors}</dd>
              <dt>Read model</dt><dd>{he.ix.readModel}</dd>
            </dl>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Pair({ k, v, cls }: { k: string; v: string; cls: string }) {
  return <><dt>{k}</dt><dd className={cls}>{v}</dd></>;
}
