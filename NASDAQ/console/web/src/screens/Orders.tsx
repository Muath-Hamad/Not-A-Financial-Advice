import { Fragment, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useHistory, usePending, useRoundTrips } from '@/api/client';
import { useConsole, useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { control, nav } from '@/domain/actions';
import { ORDERS_SUB, selectHistory, selectPending, selectRoundTrips, type SideFilter } from '@/domain/orders';
import { cx } from '@/lib/format';
import { Icon } from '@/components/icons';
import { Chip, Conf, Empty, ExportButton, Fresh, Guardrail, HBars, Lifecycle, MiniLifecycle, Note, PageHeader, Panel, Seg, SideTag, Sk, Stat, Tabs } from '@/components/ui';
import { exportCsv } from './csv';
import { Gloss, T } from '@/glossary/Term';

type Tab = 'pending' | 'history' | 'round';

export function Orders() {
  const { tab = 'pending' } = useParams();
  const navigate = useNavigate();
  const t = (['pending', 'history', 'round'].includes(tab) ? tab : 'pending') as Tab;
  const ctx = useCtx();
  const { positions } = useConsole();
  const pq = usePending();
  const hq = useHistory();
  const rq = useRoundTrips();
  const nP = pq.data ? String(selectPending(ctx, pq.data, positions).count) : '';
  return (
    <div className="page">
      <PageHeader title="Orders" sub={<Gloss text={ORDERS_SUB} />} />
      <Tabs<Tab>
        value={t} onChange={(k) => navigate('/orders/' + k)}
        items={[{ k: 'pending', l: 'Pending', n: nP }, { k: 'history', l: 'History', n: hq.data ? String(hq.data.total) : '' }, { k: 'round', l: 'Round trips', n: rq.data ? String(rq.data.trips.length) : '' }]}
      />
      {t === 'pending' && <Pending />}
      {t === 'history' && <History />}
      {t === 'round' && <RoundTrips />}
    </div>
  );
}

const PEND_COLS = '150px 84px 130px 90px 90px 100px minmax(250px, 1fr) 160px 200px 200px 230px 120px';

function Pending() {
  const ctx = useCtx();
  const { positions, dispatch, showToast } = useConsole();
  const pq = usePending();
  const [open, setOpen] = useState<string | null>(null);
  const fr = selectFresh(ctx);
  if (!pq.data) return <Panel><div className="pb"><Sk h={180} /></div></Panel>;
  const pe = selectPending(ctx, pq.data, positions);
  const owner = ctx.role === 'owner';
  const copy = (cid: string) => {
    navigator.clipboard?.writeText(cid).catch(() => undefined);
    showToast('Copied ' + cid);
  };
  return (
    <>
      <section className="panel">
        <div className="pb row wrap" style={{ gap: 20, alignItems: 'flex-start' }}>
          <div className="col gap4"><span className="up"><T k="nextOpen">Next open</T></span><span className="lg b">{pe.nextOpen}</span><span className="sm dim"><T k="submit">Submit 19:15 ET</T> (retry 19:45) · manual submit until 09:28 ET</span></div>
          <div className="col gap4"><span className="up">Status</span><span className={cx('pill static', pe.stCls)}><span className="pd" />{pe.status}</span></div>
          <span className="sp" />
          {pe.held && (
            <div className="col gap4" style={{ alignItems: 'flex-start', maxWidth: 340 }}>
              <span className="sm warn b"><T k="approval">Night held</T> — {pe.holdWhy}</span>
              {owner && <button type="button" className="btn primary" onClick={() => dispatch(control('release'))}>Release night…</button>}
              <span className="eff">Effective: <b>now</b> — submit runs with --approved; window closes 09:28 ET</span>
            </div>
          )}
          <Fresh cls={fr.model.cls} l={fr.model.s} />
        </div>
      </section>
      <section className="panel">
        <div className="ph"><h3>Orders for the next open</h3><span className="hint">{pe.hint}</span><Fresh cls={fr.model.cls} l={fr.model.s} /></div>
        {pe.none && (
          <Empty icon="orders" title={pe.noneH} actions={pe.noneAct ? <><button type="button" className="btn" onClick={() => dispatch(nav('health'))}>View details</button>{owner && <button type="button" className="btn primary" onClick={() => dispatch(control('rerun', 'Cycle A'))}>Re-run Cycle A…</button>}</> : undefined}>
            <Gloss text={pe.noneP} />
          </Empty>
        )}
        {!pe.none && (
          <>
            <div className="twrap wide-only">
              <div className="dt flush">
                <div className="dt-r dt-h" style={{ gridTemplateColumns: PEND_COLS }}>
                  <span className="stick">Symbol</span><span>Side</span><span>Quantity</span><span><T k="moo">Type</T></span><span className="r"><T k="refClose">Ref close</T></span><span className="r"><T k="estValue">Est. value</T></span><span>Reason</span><span><T k="source">Source</T></span><span><T k="guardrails">Guardrails</T></span><span><T k="lifecycle">Lifecycle</T></span><span><T k="clientOrderId">Client order id</T></span><span />
                </div>
                {pe.rows.map((o) => (
                  <Fragment key={o.id}>
                    <div className={cx('dt-r', o.rowCls)} style={{ gridTemplateColumns: PEND_COLS }}>
                      <span className="stick"><span className="sym">{o.s}</span><span className="symname">{o.n}</span></span>
                      <span><SideTag side={o.sideCls} label={o.sideL} /></span>
                      <span><span className="num">{o.qty}</span><span className="xs muted" style={{ display: 'block' }}>{o.amt}</span></span>
                      <span className="mono xs dim"><T k="moo">MOO · opg</T></span>
                      <span className="r num">{o.ref}</span>
                      <span className="r num">{o.est}</span>
                      <span className="wc dim sm"><Gloss text={o.why} /></span>
                      <span><Chip cls={o.srcCls}>{o.srcL}</Chip></span>
                      <span><Guardrail ok={o.grOk} rule={o.gr} note={o.grNote} /></span>
                      <span><MiniLifecycle steps={o.lc} state={o.state} sc={o.sc} /></span>
                      <span className="row gap4"><span className="mono xs dim">{o.cid}</span><button type="button" className="btn ghost sm icon" onClick={() => copy(o.cid)} aria-label="Copy client order id"><Icon name="copy" className="s14" /></button></span>
                      <span className="row gap4">
                        <button type="button" className="btn ghost sm" onClick={() => setOpen(open === o.id ? null : o.id)} aria-expanded={open === o.id}>{open === o.id ? 'Hide' : 'Lifecycle'}</button>
                        {o.canCancel && <button type="button" className="btn sm danger-o" onClick={() => dispatch(control('cancel_manual', o.s))}>Cancel</button>}
                      </span>
                    </div>
                    {open === o.id && <div className="dt-x"><Lifecycle steps={o.lc} style={{ maxWidth: 860 }} /></div>}
                  </Fragment>
                ))}
              </div>
            </div>
            <div className="narrow-only">
              {pe.rows.map((o) => (
                <div key={o.id} className="mcard">
                  <span className="mcard-h"><SideTag side={o.sideCls} label={o.sideL} /><span className="sym">{o.s}</span><span className="num sm">{o.qty}</span><span className="sp" /><span className="num b">{o.est}</span></span>
                  <span className="xs dim"><Gloss text={o.why} /></span>
                  <span className="row wrap" style={{ gap: 6 }}>
                    <Chip cls={o.srcCls}>{o.srcL}</Chip><Guardrail ok={o.grOk} rule={o.gr} small /><span className="sp" />
                    <MiniLifecycle steps={o.lc} state={o.state} sc={o.sc} small />
                  </span>
                  {o.canCancel && <button type="button" className="btn danger-o block" style={{ height: 40 }} onClick={() => dispatch(control('cancel_manual', o.s))}>Cancel manual order</button>}
                </div>
              ))}
            </div>
            <div className="pf">
              <span>Buys <b className="num">{pe.buys}</b></span><span>Sells <b className="num">{pe.sells}</b></span><span><T k="netCash">Net cash need</T> <b className="num">{pe.net}</b></span>
              <span><T k="turnover">Turnover</T> <b className="num">{pe.turn}</b> <span className="muted">of 75% limit</span></span><span><T k="cashLeft">Cash left (est.)</T> <b className="num">{pe.left}</b></span>
            </div>
          </>
        )}
      </section>
    </>
  );
}

const HIST_COLS = '34px 92px 92px 70px 64px 56px 92px 92px 84px 74px 84px 96px 60px 96px 50px 140px 90px minmax(280px, 1fr)';

function History() {
  const ctx = useCtx();
  const hq = useHistory();
  const [side, setSide] = useState<SideFilter>('all');
  const [open, setOpen] = useState<string | null>('h1');
  const fr = selectFresh(ctx);
  const hi = useMemo(() => (hq.data ? selectHistory(ctx, hq.data, side) : null), [ctx, hq.data, side]);
  if (!hi) return <Panel><div className="pb"><Sk h={300} /></div></Panel>;
  const onExport = () => exportCsv('orders_since_' + hq.data!.since + '.csv',
    ['Decision', 'Fill', 'Symbol', 'Side', 'Qty', 'Decision close', 'Official open', 'Fill price', 'Slip bps', 'Shortfall bps', 'Value', 'Fees', 'Realized', 'Days', 'Client order id', 'Reason'],
    hi.rows.map((o) => [o.dd, o.fd, o.s, o.side, o.q, o.dc, o.op, o.fp, o.slip, o.sf, o.val, o.fee, o.rp, o.days, o.cid, o.why]));
  return (
    <>
      <div className="row wrap" style={{ gap: 8 }}>
        <Seg<SideFilter> label="Side" value={side} onChange={setSide} items={[{ k: 'all', l: 'All' }, { k: 'BUY', l: 'Buys' }, { k: 'SELL', l: 'Sells' }]} />
        <span className="sp" />
        <ExportButton onClick={onExport} />
      </div>
      <section className="panel">
        <div className="ph"><h3>Order history</h3><span className="hint">{hi.hint}</span><Fresh cls={fr.acct.cls} l={fr.acct.l} /></div>
        <div className="twrap" style={{ maxHeight: 620 }}>
          <div className="dt flush dense">
            <div className="dt-r dt-h" style={{ gridTemplateColumns: HIST_COLS }}>
              <span /><span>Decision</span><span>Fill</span><span>Symbol</span><span>Side</span><span className="r">Qty</span><span className="r"><T k="decisionClose">Decision close</T></span><span className="r"><T k="officialOpen">Official open</T></span><span className="r"><T k="fillPrice">Fill price</T></span><span className="r"><T k="slippage">Slip</T> <T k="bps">bps</T></span><span className="r"><T k="shortfall">Shortfall</T></span><span className="r"><T k="value">Value</T></span><span className="r"><T k="fees">Fees</T></span><span className="r"><T k="realized">Realized</T></span><span className="r"><T k="session">Days</T></span><span><T k="reconcile">Status</T></span><span><T k="source">Source</T></span><span>Reason</span>
            </div>
            {hi.rows.map((o) => (
              <Fragment key={o.id}>
                <div className={cx('dt-r', open === o.id && 'sel')} style={{ gridTemplateColumns: HIST_COLS }}>
                  <span><button type="button" className="btn ghost sm icon" onClick={() => setOpen(open === o.id ? null : o.id)} aria-label={'Show lifecycle for ' + o.s} aria-expanded={open === o.id}>{open === o.id ? '▾' : '▸'}</button></span>
                  <span className="num">{o.dd}</span><span className="num">{o.fd}</span><span className="sym">{o.s}</span>
                  <span><SideTag side={o.sideCls} label={o.side} /></span>
                  <span className="r num">{o.q}</span><span className="r num">{o.dc}</span><span className="r num">{o.op}</span><span className="r num">{o.fp}</span>
                  <span className={cx('r num', o.slipCls)}>{o.slip}</span><span className="r num dim">{o.sf}</span><span className="r num">{o.val}</span><span className="r num muted">{o.fee}</span>
                  <span className={cx('r num', o.rpCls)}>{o.rp}</span><span className="r num">{o.days}</span>
                  <span><span className="lc"><span className="dot ok" />{o.st}</span>{o.hasAdj && <span className="xs warn" style={{ display: 'block' }}>{o.adjS}</span>}</span>
                  <span><Chip>Agent</Chip></span>
                  <span className="dim wc"><Gloss text={o.why} /></span>
                </div>
                {open === o.id && (
                  <div className="dt-x">
                    <div className="row wrap" style={{ gap: 24, alignItems: 'flex-start' }}>
                      <div className="col" style={{ gap: 10, flex: '1 1 520px', minWidth: 0 }}>
                        <span className="up">Lifecycle · client order id <span className="mono" style={{ textTransform: 'none', letterSpacing: 0 }}>{o.cid}</span></span>
                        <Lifecycle steps={o.lc} />
                        {o.hasAdj && <Note tone="warn">{o.adj}</Note>}
                      </div>
                      <div className="col" style={{ gap: 6, flex: '1 1 340px', minWidth: 0 }}>
                        <span className="up">Raw record · orders/{o.file}.json</span>
                        <pre className="code" style={{ margin: 0, maxHeight: 220 }}>{o.json}</pre>
                      </div>
                    </div>
                  </div>
                )}
              </Fragment>
            ))}
          </div>
        </div>
        <div className="pf"><span>{hi.foot}</span><span className="sp" /><span className="muted"><T k="slippage">Slippage</T> = fill − official open (signed by side, + is a cost) · <T k="shortfall">Shortfall</T> = fill − decision close</span></div>
      </section>
    </>
  );
}

const RT_COLS = '70px 64px 64px 50px 84px 84px 100px 72px 120px 100px';

function RoundTrips() {
  const ctx = useCtx();
  const rq = useRoundTrips();
  const fr = selectFresh(ctx);
  if (!rq.data) return <Panel><div className="pb"><Sk h={300} /></div></Panel>;
  const rt = selectRoundTrips(rq.data.trips, rq.data.fees);
  return (
    <>
      <div className="g4">
        <Stat l={<T k="winRate">Win rate</T>} v={rt.win} s={<Gloss text={rt.winN} />} />
        <Stat l={<T k="avgWinLoss">Average win / average loss</T>} v={<><span className="pos">{rt.avgW}</span> <span className="muted">/</span> <span className="neg">{rt.avgL}</span></>} s={<><T k="payoff">payoff ratio</T> {rt.payoff}</>} />
        <Stat l={<T k="profitFactor">Profit factor</T>} v={rt.pf} s="gross wins ÷ gross losses" />
        <Stat l={<T k="realized">Realized since start</T>} v={rt.tot} vCls={rt.totCls} s={rt.totN} />
      </div>
      <div className="g12">
        <Panel className="c5" title={<><T k="pnl">P&amp;L</T> by exit reason</>} fresh={{ cls: fr.model.cls, l: fr.model.s }}>
          <HBars items={rt.byR} wrapLabel />
        </Panel>
        <Panel className="c7" title={<T k="roundTrip">Round trips</T>} hint={<>one row per closed position · <T k="fifo">FIFO</T></>} fresh={{ cls: fr.model.cls, l: fr.model.s }}>
          <div className="twrap" style={{ maxHeight: 520 }}>
            <div className="dt flush dense">
              <div className="dt-r dt-h" style={{ gridTemplateColumns: RT_COLS }}><span>Symbol</span><span>Entry</span><span>Exit</span><span className="r">Days</span><span className="r">Entry px</span><span className="r">Exit px</span><span className="r"><T k="pnl">P&amp;L</T></span><span className="r">P&amp;L %</span><span>Exit reason</span><span><T k="confidence">Conf. at entry</T></span></div>
              {rt.rows.map((r) => (
                <div key={r.s + r.x} className="dt-r" style={{ gridTemplateColumns: RT_COLS }}>
                  <span className="sym">{r.s}</span><span className="num">{r.e}</span><span className="num">{r.x}</span><span className="r num">{r.d}</span><span className="r num">{r.ep}</span><span className="r num">{r.xp}</span>
                  <span className={cx('r num', r.cls)}>{r.pnl}</span><span className={cx('r num', r.cls)}>{r.pct}</span>
                  <span title={r.why}><Chip><Gloss text={r.r} /></Chip></span><span><Conf c={r.c} band={r.band} bandL={r.bandL} bar={false} /></span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </>
  );
}
