import { useMemo, useState } from 'react';
import { useCompliance, useRoadmap } from '@/api/client';
import { useConsole, useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { RANGES, selectCompStrip, selectEquity, selectOverview, selectPhase, type Range } from '@/domain/overview';
import type { HoldingRow } from '@/domain/core';
import { cx } from '@/lib/format';
import { EquityChart } from '@/components/charts/EquityChart';
import { Icon, ToneIcon } from '@/components/icons';
import { BookTag, Chip, Conf, Fresh, Grade, PageHeader, Panel, Seg, Shar, Spark, StackBar } from '@/components/ui';

export function Overview() {
  const ctx = useCtx();
  const { overview, positions, intents, nextOpen, dispatch, go, openDrawer } = useConsole();
  const rq = useRoadmap();
  const cq = useCompliance();
  const [range, setRange] = useState<Range>('all');
  const fr = selectFresh(ctx);
  const ov = useMemo(() => selectOverview(ctx, overview!, positions, intents, rq.data?.decisions ?? [], nextOpen), [ctx, overview, positions, intents, rq.data, nextOpen]);
  const eq = useMemo(() => selectEquity(ctx, overview!, range), [ctx, overview, range]);
  const ph = selectPhase(overview!);
  const cs = selectCompStrip(ctx, positions, cq.data?.universe ?? []);

  return (
    <div className="page">
      <PageHeader title="Overview" sub={ov.sub}>
        <span className="sp" />
        <Fresh cls={fr.model.cls} l={fr.model.l} style={{ marginLeft: 0 }} />
      </PageHeader>

      <div className="kpis">
        <div className="kpi">
          <div className="kpi-l">Equity<BookTag>MODEL</BookTag></div>
          <div className="kpi-v">{ov.eq}</div>
          <div className="kpi-d"><span className={ov.eqCls}>{ov.eqSince}</span><span className="muted"> since start · IXIC </span><span className={ov.ixCls}>{ov.ixic}</span></div>
          <div className="kpi-spark"><Spark d={ov.sEq} /></div>
          <div className="kpi-s">{ov.eqAcct}</div>
        </div>
        <div className="kpi">
          <div className="kpi-l">Today’s P&amp;L<BookTag>MODEL</BookTag></div>
          <div className={cx('kpi-v', ov.dayCls)}>{ov.day}</div>
          <div className="kpi-d"><span className={ov.dayCls}>{ov.dayP}</span><span className="muted"> · {ov.dayWhen}</span></div>
          <div className="kpi-spark"><Spark d={ov.sDay} /></div>
          <div className="kpi-s">{ov.dayAcct}</div>
        </div>
        <div className="kpi">
          <div className="kpi-l">Drawdown from peak</div>
          <div className="kpi-v neg">{ov.dd}</div>
          <div className="kpi-d muted">peak {ov.peak} · max {ov.mdd}</div>
          <div className="gauge" style={{ marginTop: 9 }}>
            <div className="gauge-t"><i className="gauge-f" style={{ width: ov.ddW + '%' }} /><i className="gauge-ref" style={{ left: '64.8%' }} /><i className="gauge-th" style={{ left: 'calc(100% - 2px)' }} /></div>
            <div className="gauge-lbl"><span>0%</span><span>ref −16.2%</span><span className="danger">kill −25%</span></div>
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-l">Exposure<BookTag>MODEL</BookTag></div>
          <div className="kpi-v">{ov.exp}<span className="muted" style={{ fontSize: 12, fontWeight: 500 }}> invested</span></div>
          <div className="kpi-d muted">cash {ov.cash}</div>
          <div className="bar" style={{ marginTop: 11, height: 8 }}><i className="bar-f" style={{ width: ov.expW + '%' }} /><i className="capmk" style={{ left: '95%' }} title="EXP_MAX 0.95" /></div>
          <div className="kpi-s" style={{ marginTop: 7 }}>{ov.expAcct}</div>
        </div>
        <div className="kpi">
          <div className="kpi-l">Positions</div>
          <div className="kpi-v">{ov.pos}<span className="muted" style={{ fontSize: 12, fontWeight: 500 }}> of 15 max</span></div>
          <div className="kpi-d muted">{ov.posFree} slots free · largest {ov.largest}</div>
          <div className="slots" style={{ marginTop: 11 }}>{ov.slots.map((f, i) => <span key={i} className={f ? 'f' : ''} />)}</div>
          <div className="kpi-s" style={{ marginTop: 7 }}>position cap 18% · {ov.underRev}</div>
        </div>
        <div className="kpi">
          <div className="kpi-l">Orders for next open</div>
          <div className="kpi-v">{ov.ord}</div>
          <div className="kpi-d dim">{ov.ordSplit}</div>
          <div className="row wrap gap4" style={{ marginTop: 8 }}><Chip>{ov.ordWhen}</Chip>{ov.ordBlk && <Chip cls="danger">{ov.ordBlkL}</Chip>}</div>
          <div className="kpi-s" style={{ marginTop: 6 }}>{ov.ordNote}</div>
        </div>
      </div>

      <div className="g12">
        <section className="panel c8">
          <div className="ph">
            <h3>Equity</h3><span className="hint wide-only">rebased to $100k · since Tue 18 Aug</span>
            <Seg label="Range" value={range === 'all' ? 'Since start' : range} onChange={(k) => setRange(RANGES.find((r) => r.l === k)!.k)} items={RANGES.map((r) => ({ k: r.l, l: r.l }))} />
            <Fresh cls={fr.model.cls} l={fr.model.s} />
          </div>
          <div className="pb">
            <Legend eq={eq} />
            <EquityChart
              v={eq} mainH={230} ddH={78}
              ddLabel={<div className="row" style={{ marginTop: 14, gap: 8 }}><span className="up">Drawdown</span><span className="xs muted">vs −16.2% OOS reference and −25% kill line</span></div>}
            />
          </div>
        </section>

        <section className="panel c4">
          <div className="ph"><h3>Attention</h3><span className={cx('cnt', ov.attCls)}>{ov.attN}</span><Fresh cls={fr.ledger.cls} l={fr.ledger.l} /></div>
          <div className="att">
            {ov.att.map((a) => (
              <div key={a.t} className="att-i">
                <span className={cx('att-ico', a.tone)}><ToneIcon tone={a.tone} /></span>
                <div className="att-t">{a.t}<span className="s">{a.s}</span></div>
                <button type="button" className="btn sm" onClick={() => dispatch(a.intent)}>{a.btn}</button>
              </div>
            ))}
          </div>
        </section>

        <section className="panel c8">
          <div className="ph">
            <h3>Holdings</h3><span className="hint">{ov.snapHint}</span><span className="sp" />
            <button type="button" className="btn sm ghost" onClick={() => go('holdings')}>Open Holdings →</button>
            <Fresh cls={fr.model.cls} l={fr.model.s} style={{ marginLeft: 0 }} />
          </div>
          <SnapshotTable rows={ov.rows} onOpen={openDrawer} />
          <div className="narrow-only">
            {ov.rows.map((h) => <HoldingCard key={h.s} h={h} onOpen={openDrawer} pct />)}
          </div>
        </section>

        <div className="col c4" style={{ gap: 16 }}>
          <Panel title="Phase & gate" fresh={fr.ledger} footer={<><Chip cls="warn">{ph.dec}</Chip><span className="sp" /><button type="button" className="btn sm ghost" onClick={() => go('roadmap')}>Roadmap →</button></>}>
            <div className="pb row" style={{ gap: 16, alignItems: 'center' }}>
              <div style={{ position: 'relative', width: 72, height: 72, flex: 'none' }}>
                <svg className="ring" viewBox="0 0 80 80"><circle className="rt" cx="40" cy="40" r="32" /><circle className="rf" cx="40" cy="40" r="32" transform="rotate(-90 40 40)" style={{ strokeDasharray: ph.dash }} /></svg>
                <span className="num" style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', fontWeight: 700, fontSize: 15 }}>{ph.ring}</span>
              </div>
              <div className="col gap4" style={{ minWidth: 0 }}>
                <span className="b">{ph.title}</span>
                <span className="sm dim">{ph.gate}</span>
                <span className="xs muted">{ph.dates}</span>
              </div>
            </div>
          </Panel>
          <Panel title="Compliance" hint="book by Sharia grade" fresh={{ l: cs.fresh }} footer={<button type="button" className="btn sm ghost" onClick={() => go('compliance')}>Compliance →</button>}>
            <div className="pb col" style={{ gap: 10 }}>
              <StackBar segs={cs.stack} />
              <div className="row wrap" style={{ gap: 12 }}>
                {cs.stack.map((g) => (
                  <span key={g.l} className="row gap4 xs"><span className={cx('grade', g.cls)} style={{ width: 18, height: 18, fontSize: 10 }}>{g.l}</span><span className="num">{g.p}</span></span>
                ))}
              </div>
              <dl className="kv left" style={{ margin: '2px 0 0' }}>
                <dt>Under review</dt><dd>{cs.rev}</dd>
                <dt>Watchlist</dt><dd>{cs.watch}</dd>
                <dt>Next re-screen</dt><dd>Fri 1 Jan 2027</dd>
                <dt>Data source</dt><dd><Chip cls="warn">Unlicensed proxy</Chip></dd>
              </dl>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}

export function Legend({ eq, adaptNote }: { eq: ReturnType<typeof selectEquity>; adaptNote?: boolean }) {
  return (
    <div className="legend">
      <span><i className="sw model" />Model <b className="num">{eq.lastM}</b></span>
      <span className={eq.acctLegCls}><i className="sw acct" />{eq.acctLeg}</span>
      <span><i className="sw bench" />NASDAQ Composite <b className="num">{eq.lastB}</b></span>
      <span className={cx('muted', !adaptNote && 'wide-only')}>
        <span className="info">◆</span> adaptation{adaptNote ? ' (none yet · next ~2 Feb 2027)' : ''} <span className="warn">⚑</span> override <span className="danger">■</span> halt
      </span>
    </div>
  );
}

const SNAP_COLS = '150px 100px 130px 120px 150px 120px minmax(190px, 1fr)';

function SnapshotTable({ rows, onOpen }: { rows: HoldingRow[]; onOpen: (s: string) => void }) {
  return (
    <div className="twrap wide-only">
      <div className="dt flush dense">
        <div className="dt-r dt-h" style={{ gridTemplateColumns: SNAP_COLS }}>
          <span className="stick">Symbol</span><span className="r">Value</span><span>Weight</span><span className="r">Unrealized</span><span>Confidence</span><span>Sharia</span><span>Nearest exit</span>
        </div>
        {rows.map((h) => (
          <div key={h.s} className="dt-r" style={{ gridTemplateColumns: SNAP_COLS }}>
            <span className="stick">
              <button type="button" className="linkbtn row gap4" onClick={() => onOpen(h.s)}>
                <span className="sym">{h.s}</span>
                {h.locked && <Icon name="lock" className="s14 warn" />}
                <span className="xs muted" style={{ maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.n}</span>
              </button>
            </span>
            <span className="r num">{h.val}</span>
            <span><WeightCell h={h} /></span>
            <span className={cx('r num', h.uCls)}>{h.uP}</span>
            <span><Conf c={h.c} band={h.band} bandL={h.bandL} segs={h.segs} title={h.cT} /></span>
            <span><Shar g={h.g} gCls={h.gCls} stat={h.stat} /></span>
            <span className={h.exCls}><span className="b">{h.exK}</span> <span className="num">{h.exP}</span> <span className="xs muted">· {h.exD}</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function WeightCell({ h }: { h: HoldingRow }) {
  return (
    <span className="wcell">
      <span className="num" style={{ width: 40 }}>{h.w}</span>
      <span className="bar"><i className="bar-f" style={{ width: h.wb + '%' }} /><i className="capmk" style={{ left: '90%' }} /></span>
    </span>
  );
}

/** Phone card for a holding row (tables become cards below 768 px). */
export function HoldingCard({ h, onOpen, pct, pending }: { h: HoldingRow; onOpen: (s: string) => void; pct?: boolean; pending?: boolean }) {
  return (
    <button type="button" className="mcard mbtn" onClick={() => onOpen(h.s)}>
      <span className="mcard-h">
        <span className="sym">{h.s}</span>
        <span className="xs muted sp" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.n}</span>
        <Grade g={h.g} gCls={h.gCls} />
        <Conf c={h.c} band={h.band} segs={h.segs} label={false} />
      </span>
      <span className="mcard-g">
        <span><span className="l">Value</span><span className="v">{h.val}</span></span>
        <span><span className="l">Weight</span><span className="v">{h.w}</span></span>
        <span><span className="l">Unrealized</span><span className={cx('v', h.uCls)}>{pct ? h.uP : h.u}</span></span>
      </span>
      {pending
        ? <span className="row xs" style={{ gap: 6 }}><span className={h.exCls}>{h.exK} {h.exP} · {h.exD}</span><span className="sp" /><span className={h.pCls}>{h.pendS}</span></span>
        : <span className={cx('xs', h.exCls)}>{h.exK} {h.exP} · {h.exD}</span>}
    </button>
  );
}
