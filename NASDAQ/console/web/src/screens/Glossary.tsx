// Every explained term in one searchable list, grouped like the screens.

import { useState } from 'react';
import { PageHeader } from '@/components/ui';
import { Icon } from '@/components/icons';
import { TERMS, type TermKey } from '@/glossary/terms';

const GROUPS: [string, TermKey[]][] = [
  ['Money and the portfolio', ['equity', 'pnl', 'todayPnl', 'unrealized', 'realized', 'drawdown', 'maxDrawdown', 'peak', 'killLine', 'refDD', 'exposure', 'cash', 'weight', 'posCap', 'avgCost', 'last', 'value', 'shares', 'maxPositions', 'expMax', 'grossCap', 'turnover', 'netCash', 'cashLeft', 'fees', 'fifo', 'roundTrip', 'winRate', 'avgWinLoss', 'payoff', 'profitFactor', 'dividend', 'withholding', 'benchmark', 'rebased', 'sinceStart']],
  ['Books and modes', ['model', 'account', 'drift', 'twin', 'ghost', 'paper', 'live', 'booktag']],
  ['Orders and execution', ['moo', 'nextOpen', 'refClose', 'estValue', 'officialOpen', 'decisionClose', 'fillPrice', 'slippage', 'bps', 'shortfall', 'clientOrderId', 'lifecycle', 'intent', 'source', 'guardrails', 'advCap', 'pauseEntries', 'excluded', 'locked', 'killSwitch', 'approval', 'halt', 'reconcile', 'submit', 'cycleA', 'cycleB']],
  ['The strategy', ['momentum', 'rank', 'rankExit', 'atr', 'initialStop', 'trailingStop', 'timeStop', 'nearestExit', 'sma', 'high52', 'sizeLine', 'deRisk', 'regime', 'sentiment', 'adapt', 'oos', 'frozen', 'session', 'universe', 'params']],
  ['Confidence', ['confidence', 'signal', 'riskRoom', 'regimeScore', 'dataScore']],
  ['Sharia compliance', ['aaoifi', 'shariaGrade', 'compliant', 'underReview', 'debtMcap', 'cashMcap', 'marketCap', 'headroom', 'pp', 'impermissible', 'purification', 'zakat', 'reviewFlag', 'ruling', 'rescreen', 'watchlist', 'businessActivity', 'commonShare', 'unlicensed']],
  ['System health', ['dataGate', 'coverage', 'fetchOk', 'crossSource', 'asof', 'determinism', 'ghostGate', 'streak', 'heartbeat', 'deadman', 'indexer', 'ledger', 'commit', 'p1p2', 'stale', 'freshness']],
  ['Roadmap', ['phase', 'gate', 'decisions']],
];

export function Glossary() {
  const [q, setQ] = useState('');
  const needle = q.trim().toLowerCase();
  const match = (k: TermKey) => {
    const e = TERMS[k];
    return !needle || (e.title + ' ' + e.plain + ' ' + ('here' in e ? e.here : '')).toLowerCase().includes(needle);
  };
  const groups = GROUPS.map(([g, keys]) => [g, keys.filter(match)] as const).filter(([, keys]) => keys.length);
  return (
    <div className="page">
      <PageHeader title="Glossary" sub="Every term and abbreviation in the console, in plain words. Anywhere you see a dotted underline, hover it (or tap it) for the same explanation." />
      <label className="search-w"><Icon name="search" /><input className="inp search" style={{ width: 300 }} placeholder="Search terms" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the glossary" /></label>
      {groups.map(([g, keys]) => (
        <section key={g} className="panel">
          <div className="ph"><h3>{g}</h3><span className="hint">{keys.length} terms</span></div>
          <dl className="pb" style={{ margin: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '14px 24px' }}>
            {keys.map((k) => {
              const e = TERMS[k];
              return (
                <div key={k} className="col gap4" id={'term-' + k}>
                  <dt className="b sm" style={{ color: 'var(--fg-1)' }}>{e.title}</dt>
                  <dd className="sm dim" style={{ margin: 0, lineHeight: 1.5 }}>{e.plain}</dd>
                  {'here' in e && e.here && <dd className="xs muted" style={{ margin: 0, lineHeight: 1.5 }}>{e.here}</dd>}
                </div>
              );
            })}
          </dl>
        </section>
      ))}
      {!groups.length && <div className="sm muted">No term matches “{q}”.</div>}
    </div>
  );
}
