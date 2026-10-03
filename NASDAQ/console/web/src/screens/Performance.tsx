// Performance (M2): equity and drawdown, metrics against the OOS reference,
// monthly returns, attribution and execution quality (docs/09 §5.4).

import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { usePerformance, useReviewMonths, useRoundTrips } from '@/api/client';
import { useConsole, useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { RANGES, selectEquity, type Range } from '@/domain/overview';
import { selectRoundTrips } from '@/domain/orders';
import { PERF_TABS, selectExecution, selectPerformance, type PerfTab } from '@/domain/performance';
import { cx } from '@/lib/format';
import { wdLabel } from '@/lib/dates';
import { EquityChart } from '@/components/charts/EquityChart';
import { Empty, Fresh, HBars, PageHeader, Panel, Seg, Sk, Stat, Tabs } from '@/components/ui';
import { T } from '@/glossary/Term';
import { Legend } from './Overview';

const METRIC_TERM: Record<string, Parameters<typeof T>[0]['k']> = {
  total: 'totalReturn', cagr: 'cagr', sharpe: 'sharpe', sortino: 'sortino', mdd: 'maxDrawdown', calmar: 'calmar', vol: 'volatility', win: 'winRate', trades: 'roundTrip',
};

export function Performance() {
  const ctx = useCtx();
  const { overview } = useConsole();
  const { '*': sub = '' } = useParams();
  const tab: PerfTab = (PERF_TABS.find((t) => t.k === sub)?.k ?? 'equity');
  const navigate = useNavigate();
  const pq = usePerformance();
  const rq = useRoundTrips();
  const mq = useReviewMonths();
  const [range, setRange] = useState<Range>('all');
  const fr = selectFresh(ctx);
  const eq = useMemo(() => (overview ? selectEquity(ctx, overview, range) : null), [ctx, overview, range]);
  const pf = useMemo(() => (pq.data ? selectPerformance(pq.data) : null), [pq.data]);
  const ex = useMemo(() => (pq.data ? selectExecution(pq.data) : null), [pq.data]);
  const rt = useMemo(() => (rq.data ? selectRoundTrips(rq.data.trips, rq.data.fees ?? 0) : null), [rq.data]);
  const [period, setPeriod] = useState<'today' | 'wtd' | 'mtd' | 'all'>('all');

  return (
    <div className="page">
      <PageHeader title="Performance" sub={pf?.sub ?? 'Model vs account vs NASDAQ Composite'}>
        <span className="sp" />
        {!!mq.data?.months.length && (
          <span className="row gap4 wide-only"><span className="xs muted"><T k="reviewPack">Review pack</T></span>
            {mq.data.months.slice(-3).map((m) => <a key={m} className="btn sm" href={'/api/review/' + m} target="_blank" rel="noreferrer">{m}</a>)}
          </span>
        )}
        <Fresh cls={fr.model.cls} l={fr.model.l} style={{ marginLeft: 0 }} />
      </PageHeader>
      <Tabs items={PERF_TABS} value={tab} onChange={(k) => navigate(k === 'equity' ? '/performance' : '/performance/' + k)} />

      {!pf && <Panel><div className="pb"><Sk h={280} /></div></Panel>}

      {pf && tab === 'equity' && (
        <>
          {eq && (
            <Panel title="Equity & drawdown" hint={<span className="wide-only"><T k="model">Model</T> vs <T k="account">Account</T> vs <T k="benchmark">NASDAQ Composite</T> · <T k="rebased">rebased to $100k</T></span>}
              extra={<Seg label="Range" value={RANGES.find((r) => r.k === range)!.l} onChange={(k) => setRange(RANGES.find((r) => r.l === k)!.k)} items={RANGES.map((r) => ({ k: r.l, l: r.l }))} />} fresh={{ cls: fr.model.cls, l: fr.model.s }}>
              <div className="pb">
                <Legend eq={eq} />
                <EquityChart v={eq} mainH={320} ddH={110}
                  ddLabel={<div className="row" style={{ marginTop: 14, gap: 8 }}><span className="up"><T k="drawdown">Drawdown</T></span><span className="xs muted">vs −16.2% <T k="refDD">OOS reference</T> and −25% <T k="killLine">kill line</T></span></div>} />
              </div>
            </Panel>
          )}
          <Panel title="Metrics" hint={'since ' + wdLabel(pq.data!.since) + ' · ' + pq.data!.sessions + ' sessions' + (pf.short ? ' — too short to judge; yearly figures are noisy' : '')} fresh={{ cls: fr.model.cls, l: fr.model.s }}
            footer={<span className="muted">{pf.refNote}</span>}>
            <div className="twrap">
              <div className="dt flush">
                <div className="dt-r dt-h" style={{ gridTemplateColumns: MCOLS }}><span>Metric</span><span className="r"><T k="model">Model</T></span><span className="r acct"><T k="account">Account</T></span><span className="r"><T k="benchmark">NASDAQ Composite</T></span><span className="r"><T k="oos">OOS reference</T></span></div>
                {pf.metrics.map((m) => (
                  <div key={m.key} className="dt-r" style={{ gridTemplateColumns: MCOLS }}>
                    <span>{METRIC_TERM[m.key] ? <T k={METRIC_TERM[m.key]}>{m.k}</T> : m.k}<span className="xs muted" style={{ display: 'block' }}>{m.n}</span></span>
                    <span className={cx('r num', m.mc)}>{m.m}</span><span className={cx('r num', m.ac)}>{m.a}</span><span className={cx('r num', m.bc)}>{m.b}</span><span className="r num b">{m.r}</span>
                  </div>
                ))}
              </div>
            </div>
          </Panel>
        </>
      )}

      {pf && tab === 'returns' && (
        <>
          <div className="row wrap" style={{ gap: 8 }}>
            <Seg label="Period" value={period} onChange={setPeriod} items={[{ k: 'today', l: 'Today' }, { k: 'wtd', l: 'Week' }, { k: 'mtd', l: 'Month' }, { k: 'all', l: 'Since start' }]} />
            <span className="sm dim"><T k="pnl">P&amp;L</T> <b className={cx('num', pf.periods[period].cls)}>{pf.periods[period].d}</b> · <b className={cx('num', pf.periods[period].cls)}>{pf.periods[period].p}</b> <span className="muted">(model)</span></span>
          </div>
          <Panel title="Monthly returns" hint="Twin rows are live; OOS rows are the out-of-sample backtest reference" fresh={{ cls: fr.model.cls, l: fr.model.s }}>
            <div className="pb twrap">
              <div className="hm">
                <span />{pf.months.map((m) => <span key={m} className="hm-h">{m}</span>)}<span className="hm-h">Year</span>
                {pf.hm.map((y) => [
                  <span key={y.l} className="hm-y">{y.l}</span>,
                  ...y.c.map((c, i) => <span key={y.l + i} className={cx('hm-c', c.cls)} style={{ background: c.bg }} title={c.t}>{c.v}</span>),
                  <span key={y.l + 't'} className={cx('hm-t', y.tCls)}>{y.t}</span>,
                ])}
              </div>
              {!pf.hm.length && <span className="sm muted">No monthly data yet.</span>}
            </div>
          </Panel>
          <div className="g12">
            <Panel className="c6" title={<T k="dividend">Dividends &amp; withholding</T>} fresh={fr.acct}
              footer={<span className="muted">Momentum holdings rarely pay dividends; withholding is a declared gap the twin does not model.</span>}>
              <div className="pb g3"><Stat l="Gross received" v={pf.dividends.gross} s="since start" /><Stat l={<T k="withholding">Withholding (30%)</T>} v={pf.dividends.wh} s="W-8BEN rate" /><Stat l="Net" v={pf.dividends.net} /></div>
            </Panel>
            <Panel className="c6" title="Return by period">
              <dl className="pb kv" style={{ margin: 0 }}>
                <dt>Today</dt><dd className={pf.periods.today.cls}>{pf.periods.today.d} · {pf.periods.today.p}</dd>
                <dt>Week to date</dt><dd className={pf.periods.wtd.cls}>{pf.periods.wtd.d} · {pf.periods.wtd.p}</dd>
                <dt>Month to date</dt><dd className={pf.periods.mtd.cls}>{pf.periods.mtd.d} · {pf.periods.mtd.p}</dd>
                <dt>Since start ({wdLabel(pq.data!.since)})</dt><dd className={pf.periods.all.cls}>{pf.periods.all.d} · {pf.periods.all.p}</dd>
              </dl>
            </Panel>
          </div>
        </>
      )}

      {pf && tab === 'attribution' && (
        <>
          <Panel title={<T k="attribution">P&amp;L by holding</T>} hint="waterfall from $0 to the since-start total · open positions, then closed trades and fees" fresh={{ cls: fr.model.cls, l: fr.model.s }}>
            {pf.wf.bars.length ? (
              <div className="pb twrap">
                <div style={{ minWidth: Math.max(480, pf.wf.bars.length * 62) }}>
                  <div className="wf" style={{ height: 240 }}>
                    <div className="hgrid" style={{ top: pf.wf.zero + '%', borderTopColor: 'var(--line-3)' }} />
                    {pf.wf.bars.map((b) => <div key={b.l} className="wf-c" title={b.t}><i className={b.cls} style={{ top: b.top + '%', height: b.h + '%' }} /><span className={cx('wf-l', b.lCls)} style={{ top: b.lt + '%' }}>{b.v}</span></div>)}
                  </div>
                  <div className="wf" style={{ height: 'auto', marginTop: 6 }}>{pf.wf.bars.map((b) => <span key={b.l} className="wf-c wf-x">{b.l}</span>)}</div>
                </div>
              </div>
            ) : <Empty icon={null} title="Nothing to attribute yet">No positions or closed trades.</Empty>}
          </Panel>
          <div className="g12">
            <Panel className="c4" title="By sector"><HBars items={pf.bySec} /></Panel>
            <Panel className="c4" title="By exit reason" hint="closed trades">{rt ? <HBars items={rt.byR} /> : <div className="pb"><Sk h={120} /></div>}</Panel>
            <Panel className="c4" title={<T k="drift">Model vs account gap</T>} fresh={fr.acct}
              footer={pf.gap ? <span>Account − Model = <b className={cx('num', (pf.gapTotal ?? 0) >= 0 ? 'pos' : 'neg')}>{pf.gap[pf.gap.length - 1].v}</b> since start</span> : undefined}>
              {pf.gap ? <HBars items={pf.gap} /> : <Empty icon={null} title="No account yet" style={{ padding: '28px 16px' }}>The gap decomposition starts with the first paper account history.</Empty>}
            </Panel>
          </div>
        </>
      )}

      {pf && tab === 'execution' && (
        ex ? (
          <>
            <div className="g4">
              <Stat l={<T k="slippage">Average slippage</T>} v={ex.avg} s="band ≤ 10 bps/side · pre-registered" />
              <Stat l="Fills outside ±10 bps" v={ex.out} vCls={ex.out !== '0' ? 'warn' : ''} s="since start" />
              <Stat l="Missed fills" v={ex.missed} s={<><T k="moo">MOO</T> auction · since start</>} />
              <Stat l={<T k="drift">Tracking error to twin</T>} v={ex.te} s="latest month · band < 0.5%/month" />
            </div>
            <div className="g12">
              <Panel className="c8" title="Slippage per fill" hint={<><T k="bps">bps</T> vs the official open · + is a cost · band ±10 bps</>} fresh={fr.acct}>
                {ex.has ? (
                  <div className="pb">
                    <div className="legend"><span><span className="scat" style={DOT} />buy</span><span><span className="scat sell" style={DOT} />sell</span><span><span className="scat out" style={DOT} />outside band</span></div>
                    <div className="chart" style={{ height: 240, marginTop: 8 }}>
                      <div className="plot" style={{ right: 52, top: 8, bottom: 22 }}>
                        <div className="band" style={{ top: ex.bandTop + '%', height: ex.bandH + '%' }} />
                        {ex.yt.map((y) => <span key={y.l}><div className="hgrid" style={{ top: y.p + '%' }} /><span className="ax-y in" style={{ top: y.p + '%' }}>{y.l}</span></span>)}
                        {ex.pts.map((p, i) => <span key={i} className={cx('scat', p.cls)} style={{ left: p.x + '%', bottom: p.y + '%' }} title={p.t} />)}
                        {ex.xt.map((x) => <span key={x.l + x.p} className="ax-x in" style={{ left: x.p + '%' }}>{x.l}</span>)}
                      </div>
                    </div>
                  </div>
                ) : <Empty icon={null} title="No fills yet">Slippage is measured from the first paper fill against the official open.</Empty>}
              </Panel>
              <Panel className="c4" title={<T k="drift">Tracking error to twin</T>} hint="monthly · band 0.5%">
                <div className="pb">
                  {ex.teBars.length ? (
                    <div className="vbars" style={{ height: 180 }}>
                      <div className="hl" style={{ top: ex.teBand + '%', borderTopStyle: 'dashed' }} />
                      {ex.teBars.map((b) => <div key={b.l} className="vbar"><span className={cx('xs num', b.over && 'danger')}>{b.v}</span><i style={{ height: b.h + '%', background: b.over ? 'var(--danger)' : 'var(--acct)' }} /><span className="xs muted">{b.l}</span></div>)}
                    </div>
                  ) : <span className="sm muted">Needs at least one month of account history.</span>}
                  <div className="xs muted" style={{ marginTop: 8 }}>Dashed line = 0.5%/month band.</div>
                </div>
              </Panel>
            </div>
          </>
        ) : (
          <Panel><Empty icon="clock" title="No account in Ghost">The twin fills at the official open by construction, so slippage is zero. Real slippage, missed fills and tracking error are measured from the first paper fill.</Empty></Panel>
        )
      )}
    </div>
  );
}

const MCOLS = 'minmax(170px, 1fr) 130px 130px 150px 170px';
const DOT = { position: 'static', transform: 'none', display: 'inline-block' } as const;
