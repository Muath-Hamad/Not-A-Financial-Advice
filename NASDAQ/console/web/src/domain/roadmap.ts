// Roadmap screen: docs/07 phases with live gates, owner decisions D1–D8 and
// the task list. Ported from vmRoadmap.

import type { RoadmapPayload } from '@/api/types';

const STATUS_L = { done: 'Done', open: 'Open', conditional: 'Conditional', option: 'Option' } as const;
export const TASK_GROUPS = ['all', 'G', 'P', 'E', 'U', 'R', 'S', 'X'] as const;
export type TaskGroup = (typeof TASK_GROUPS)[number];

const countdown = (d: number) => (d === 0 ? 'today' : 'in ' + d + ' day' + (d === 1 ? '' : 's'));

export function selectRoadmap(r: RoadmapPayload, group: TaskGroup) {
  const cur = r.current;
  const phases = r.phases.map((p, i) => {
    const cls = i < cur ? 'done' : i === cur ? (r.currentFailing && i === 0 ? 'cur fail' : 'cur') : 'todo';
    const gates = p.gates.map((g) => {
      const ok = i < cur ? true : g.ok;
      return { g: ok === true ? '✓' : ok === false ? '✕' : '○', cls: ok === true ? 'pos' : ok === false ? 'danger' : 'muted', l: g.label };
    });
    return { n: p.n, l: p.label, d: p.dates, cls, gates };
  });
  return {
    phases,
    dec: r.decisions.map((d) => ({
      id: d.id, t: d.title, r: d.recommendation, due: d.due,
      soon: d.daysLeft != null && d.daysLeft <= 14, cd: d.daysLeft != null ? countdown(d.daysLeft) : '',
      st: d.status, stCls: d.status === 'Open' ? 'warn' : 'info',
    })),
    tasks: r.tasks.filter((t) => group === 'all' || t.group === group).map((t) => ({
      id: t.id, t: t.task, o: t.owner, due: t.due,
      st: STATUS_L[t.status], stCls: t.status === 'done' ? 'pos' : t.status === 'open' ? '' : 'info',
      soon: t.daysLeft != null && t.daysLeft <= 14 && t.status !== 'done', cd: t.daysLeft != null ? countdown(t.daysLeft) : '',
    })),
  };
}
