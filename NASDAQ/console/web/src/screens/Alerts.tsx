// Alerts inbox (M2): P1/P2 with acknowledge and resolve-with-note, linked to
// the source cycle and GitHub issue; P1 is also pushed via ntfy.

import { useState } from 'react';
import { useAlertAction } from '@/api/client';
import type { Alert } from '@/api/types';
import { useConsole, useCtx } from '@/app/console';
import { sortAlerts } from '@/domain/core';
import { cx } from '@/lib/format';
import { Chip, Empty, PageHeader, Seg } from '@/components/ui';
import { Gloss, T } from '@/glossary/Term';

type Filter = 'open' | 'p1' | 'ack' | 'resolved' | 'all';

export function filterAlerts(list: Alert[], fl: Filter): Alert[] {
  const s = sortAlerts(list);
  if (fl === 'open') return s.filter((a) => a.status !== 'resolved');
  if (fl === 'p1') return s.filter((a) => a.priority === 'P1' && a.status !== 'resolved');
  if (fl === 'ack') return s.filter((a) => a.status === 'acknowledged');
  if (fl === 'resolved') return s.filter((a) => a.status === 'resolved');
  return s;
}

const ST: Record<Alert['status'], [string, string]> = { open: ['Open', 'danger'], acknowledged: ['Acknowledged', 'warn'], resolved: ['Resolved', 'pos'] };

export function Alerts() {
  const { alerts, showToast } = useConsole();
  const ctx = useCtx();
  const act = useAlertAction();
  const [fl, setFl] = useState<Filter>('open');
  const [resolving, setResolving] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const rows = filterAlerts(alerts, fl);
  const n = (f: Filter) => filterAlerts(alerts, f).length;
  const owner = ctx.role === 'owner';
  const run = (id: string, kind: 'ack' | 'resolve') =>
    act.mutate({ id, kind, note: kind === 'resolve' ? note.trim() : undefined }, {
      onSuccess: () => { showToast(kind === 'ack' ? 'Alert ' + id + ' acknowledged' : 'Alert ' + id + ' resolved'); setResolving(null); setNote(''); },
      onError: (e) => showToast('Not saved: ' + (e as Error).message),
    });
  return (
    <div className="page">
      <PageHeader title="Alerts" sub={<><T k="p1p2">P1</T> = act now (pushed to the phone via ntfy) · P2 = review today · each links its source cycle and GitHub issue</>} />
      <div className="row wrap" style={{ gap: 8 }}>
        <Seg label="Filter" value={fl} onChange={setFl} items={[
          { k: 'open', l: 'Open · ' + n('open') }, { k: 'p1', l: 'P1 · ' + n('p1') }, { k: 'ack', l: 'Acknowledged · ' + n('ack') }, { k: 'resolved', l: 'Resolved · ' + n('resolved') }, { k: 'all', l: 'All' },
        ]} />
        <span className="sp" /><span className="xs muted">Routing: Settings → Notifications</span>
      </div>
      <section className="panel">
        {!rows.length && <Empty icon="check" title="Nothing here">No alerts match this filter.</Empty>}
        <div className="att">
          {rows.map((a) => (
            <div key={a.id} className="att-i" style={{ alignItems: 'flex-start', gap: 12, padding: '12px 14px' }}>
              <span className={cx('sev', a.priority === 'P1' ? 'p1' : 'p2')}>{a.priority}</span>
              <div className="att-t">
                <span className="b"><Gloss text={a.title} /></span>
                <span className="s" style={{ whiteSpace: 'normal' }}><Gloss text={a.detail} /></span>
                <span className="row wrap xs muted" style={{ gap: 10, marginTop: 5 }}>
                  <span className="mono">{a.id}</span><span>{a.source}</span><span>· {a.raisedAt}</span>
                  {a.githubIssue && <span className="a mono">GitHub {a.githubIssue}</span>}
                  <Chip cls={ST[a.status][1]}>{ST[a.status][0]}</Chip>
                </span>
                {a.note && <span className="xs dim" style={{ display: 'block', marginTop: 5 }}>Note: {a.note}</span>}
                {resolving === a.id && (
                  <span className="row" style={{ gap: 8, marginTop: 8 }}>
                    <input className="inp sp" placeholder="Resolution note (required)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Resolution note" autoFocus />
                    <button type="button" className="btn sm primary" onClick={() => run(a.id, 'resolve')} disabled={note.trim().length < 3 || act.isPending}>Resolve</button>
                    <button type="button" className="btn sm ghost" onClick={() => { setResolving(null); setNote(''); }}>Cancel</button>
                  </span>
                )}
              </div>
              {owner && a.status !== 'resolved' && resolving !== a.id && (
                <div className="row gap4" style={{ flex: 'none' }}>
                  {a.status === 'open' && <button type="button" className="btn sm" onClick={() => run(a.id, 'ack')} disabled={act.isPending}>Acknowledge</button>}
                  <button type="button" className="btn sm" onClick={() => { setResolving(a.id); setNote(''); }}>Resolve…</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
