import { useState } from 'react';
import { useRoadmap } from '@/api/client';
import { useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { selectRoadmap, TASK_GROUPS, type TaskGroup } from '@/domain/roadmap';
import { cx } from '@/lib/format';
import { Chip, PageHeader, Panel, Seg, Sk } from '@/components/ui';
import { Gloss, T } from '@/glossary/Term';

export function Roadmap() {
  const ctx = useCtx();
  const rq = useRoadmap();
  const [group, setGroup] = useState<TaskGroup>('all');
  const fr = selectFresh(ctx);
  const sub = 'docs/07 route · ghost → paper → evaluation → private build → real money · gates show live pass / fail';
  if (!rq.data) return <div className="page"><PageHeader title="Roadmap" sub={sub} /><Panel><div className="pb"><Sk h={200} /></div></Panel></div>;
  const rm = selectRoadmap(rq.data, group);
  return (
    <div className="page">
      <PageHeader title="Roadmap" sub={sub} />
      <Panel title={<><T k="phase">Phases</T> &amp; <T k="gate">gates</T></>} fresh={fr.ledger}>
        <div className="pb twrap">
          <div style={{ minWidth: 980, display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 0 }}>
            {rm.phases.map((p) => (
              <div key={p.n} className="col" style={{ gap: 10, paddingRight: 14 }}>
                <div className="stp"><div className={cx('stp-i', p.cls)} style={{ paddingRight: 0 }}><span className="stp-dot">{p.n}</span><span className="stp-l">{p.l}</span><span className="stp-s">{p.d}</span></div></div>
                <div className="col" style={{ gap: 5 }}>
                  {p.gates.map((g) => (
                    <span key={g.l} className="row xs" style={{ gap: 6, alignItems: 'flex-start' }}><span className={cx(g.cls, 'b')} style={{ width: 12, flex: 'none' }}>{g.g}</span><span className="dim" style={{ lineHeight: 1.4 }}><Gloss text={g.l} /></span></span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </Panel>
      <div className="g12">
        <Panel className="c6" title={<T k="decisions">Owner decisions</T>} hint="D1–D8 · only you can make these">
          <div className="twrap">
            <div className="dt flush">
              <div className="dt-r dt-h" style={{ gridTemplateColumns: '50px minmax(220px, 1fr) 130px 120px' }}><span>ID</span><span>Decision · recommendation</span><span>Needed by</span><span>Status</span></div>
              {rm.dec.map((d) => (
                <div key={d.id} className="dt-r" style={{ gridTemplateColumns: '50px minmax(220px, 1fr) 130px 120px' }}>
                  <span className="mono b">{d.id}</span>
                  <span className="wc"><span className="b sm">{d.t}</span><span className="xs muted" style={{ display: 'block', lineHeight: 1.4 }}><Gloss text={d.r} /></span></span>
                  <span className="num">{d.due}{d.soon && <Chip cls="warn" style={{ display: 'flex', width: 'max-content', marginTop: 3 }}>{d.cd}</Chip>}</span>
                  <span><Chip cls={d.stCls}>{d.st}</Chip></span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
        <Panel className="c6" title="Task list" extra={<Seg<TaskGroup> label="Task group" value={group} onChange={setGroup} items={TASK_GROUPS.map((k) => ({ k, l: k === 'all' ? 'All' : k }))} />}>
          <div className="twrap" style={{ maxHeight: 560 }}>
            <div className="dt flush dense">
              <div className="dt-r dt-h" style={{ gridTemplateColumns: '44px minmax(220px, 1fr) 96px 120px 100px' }}><span>ID</span><span>Task</span><span>Owner</span><span>Due</span><span>Status</span></div>
              {rm.tasks.map((t) => (
                <div key={t.id} className="dt-r" style={{ gridTemplateColumns: '44px minmax(220px, 1fr) 96px 120px 100px' }}>
                  <span className="mono b">{t.id}</span><span className="wc sm" style={{ lineHeight: 1.4 }}><Gloss text={t.t} /></span><span className="xs dim">{t.o}</span>
                  <span className="num xs">{t.due}{t.soon && <Chip cls="warn" style={{ display: 'flex', width: 'max-content', marginTop: 3 }}>{t.cd}</Chip>}</span>
                  <span><Chip cls={t.stCls}>{t.st}</Chip></span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
