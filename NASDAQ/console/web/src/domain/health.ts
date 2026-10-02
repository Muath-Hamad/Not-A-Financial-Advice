// Health screen: cycle timeline, ghost gate, data gate, broker, heartbeats
// and the indexer. Ported from vmHealth.

import type { CellStatus, HealthPayload } from '@/api/types';

const KN = { A: 'Cycle A', S: 'Submit', B: 'Cycle B' } as const;
const GLYPH: Record<CellStatus, string | null> = { ok: null, fail: '✕', held: '‖', skip: '·' };

export function selectHealth(h: HealthPayload, selCell: string | null) {
  const sel = selCell && h.records[selCell] ? selCell : h.defaultCell;
  const sk = sel.charAt(0) as 'A' | 'S' | 'B';
  const si = parseInt(sel.slice(1), 10);
  const ss = h.cycles[sk][si];
  const sday = h.sessions[si].dow + ' ' + h.sessions[si].label;
  return {
    sub: h.summary,
    pill: h.degraded ? 'Degraded' : 'Healthy',
    pillCls: h.degraded ? 'red' : 'green',
    days: h.sessions.map((d) => ({ w: d.dow, l: d.label })),
    rows: (['A', 'S', 'B'] as const).map((k) => ({
      k,
      c: h.sessions.map((d, i) => {
        const s = h.cycles[k][i];
        return { id: k + i, cls: s + (k + i === sel ? ' sel' : ''), g: GLYPH[s] || k, t: KN[k] + ' · ' + d.dow + ' ' + d.label + ' · ' + s };
      }),
    })),
    selT: 'Raw record · ' + KN[sk] + ' · ' + sday + ' · ' + ss,
    selJ: JSON.stringify(h.records[sel], null, 2),
    gate: {
      streak: String(h.gate.streak),
      target: String(h.gate.target),
      cls: h.gate.stalled ? 'danger' : 'warn',
      l: h.gate.stalled ?? 'In progress',
      slots: Array.from({ length: h.gate.target }, (_, i) => i < h.gate.streak),
      note: 'Earliest pass ' + h.gate.earliestPass + ' · zero open P1 required · rehearsal must send what the ledger says',
      hashes: h.gate.hashes,
      sha: h.gate.lastSha256,
      replay: h.gate.replayNote,
    },
    dg: {
      when: h.dataGate.when,
      cls: h.dataGate.tripped ? 'red' : '',
      l: h.dataGate.tripped ?? 'Passed',
      checks: h.dataGate.checks.map((c) => ({
        g: c.ok === true ? '✓' : c.ok === false ? '✕' : '!',
        cls: c.ok === true ? 'pos' : c.ok === false ? 'danger' : 'warn',
        l: c.label, v: c.value, min: c.min,
      })),
      missing: h.dataGate.missing
        ? { title: 'Symbols without a bar at asof · ' + h.dataGate.missing.count + ' of ' + h.dataGate.missing.total, sample: h.dataGate.missing.sample, more: '+' + (h.dataGate.missing.count - h.dataGate.missing.sample.length) + ' more', note: h.dataGate.missing.note }
        : null,
    },
    broker: h.broker,
    hb: h.heartbeats,
    ix: { cls: h.indexer.down ? 'red' : '', ...h.indexer },
  };
}
