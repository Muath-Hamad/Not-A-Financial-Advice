// Audit log (M1): every control change and command — git history of
// controls.json and halt.json, console records and broker commands — plus
// sign-ins. Read-only; the ledger is the record.

import { useAudit } from '@/api/client';
import { useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { cx } from '@/lib/format';
import { Chip, Empty, ExportButton, PageHeader, Panel, Sk } from '@/components/ui';
import { Gloss, T } from '@/glossary/Term';
import { exportCsv } from './csv';

const COLS = '120px 130px minmax(180px, 1.2fr) 210px minmax(180px, 1fr) 130px 76px 120px';

export function resCls(res: string): string {
  return res.startsWith('Not') ? 'danger' : res.includes('dry') ? 'warn' : 'pos';
}

export function Audit() {
  const ctx = useCtx();
  const q = useAudit();
  const fr = selectFresh(ctx);
  const rows = q.data?.rows ?? [];
  const logins = q.data?.logins ?? [];
  const exp = () => exportCsv('audit.csv', ['time', 'actor', 'action', 'before_after', 'reason', 'effective', 'commit', 'result'], rows.map((r) => [r.at, r.actor, r.act, r.ba, r.reason, r.eff, r.sha, r.res]));
  return (
    <div className="page">
      <PageHeader title={<T k="audit">Audit log</T>} sub="Immutable · every control change and command — git history of controls.json and halt.json plus console records">
        <span className="sp" />
        <ExportButton onClick={exp} />
      </PageHeader>
      <Panel title="Control changes & commands" hint={rows.length + ' entries · newest first'} fresh={fr.ledger}>
        {!q.data && <div className="pb"><Sk h={200} /></div>}
        {q.data && !rows.length && <Empty icon={null} title="No control changes yet">Every change made from Controls appears here with its reason and commit.</Empty>}
        {!!rows.length && (
          <div className="twrap">
            <div className="dt flush" style={{ minWidth: 1100 }}>
              <div className="dt-r dt-h" style={{ gridTemplateColumns: COLS }}><span>Time (ET)</span><span>Actor</span><span>Action</span><span>Before → after</span><span>Reason</span><span><T k="effective">Effective at</T></span><span><T k="commit">Commit</T></span><span>Result</span></div>
              {rows.map((r, i) => (
                <div key={r.at + r.sha + i} className={cx('dt-r', r.res.startsWith('Not') && 'warnrow')} style={{ gridTemplateColumns: COLS }}>
                  <span className="num">{r.t}</span><span className="mono xs">{r.actor}</span><span className="b wc">{r.act}</span>
                  <span className="mono xs dim wc">{r.ba}</span><span className="dim wc"><Gloss text={r.reason} /></span><span className="xs wc">{r.eff}</span>
                  <span className="mono">{r.sha}</span><span><Chip cls={resCls(r.res)}>{r.res}</Chip></span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Panel>
      {!!logins.length && (
        <Panel title="Sign-ins" hint="latest 100 · failures and lockouts included">
          <div className="twrap">
            <div className="dt flush dense">
              <div className="dt-r dt-h" style={{ gridTemplateColumns: '170px 130px 150px minmax(200px, 1fr)' }}><span>Time (UTC)</span><span>User</span><span>Event</span><span>Detail</span></div>
              {logins.map((l, i) => (
                <div key={l.at + i} className="dt-r" style={{ gridTemplateColumns: '170px 130px 150px minmax(200px, 1fr)' }}>
                  <span className="num xs">{l.at.replace('T', ' ').slice(0, 19)}</span><span className="mono xs">{l.user}</span>
                  <span className={cx('xs', /fail|lock/i.test(l.event) ? 'danger' : '')}>{l.event}</span><span className="xs dim">{l.detail}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
}
