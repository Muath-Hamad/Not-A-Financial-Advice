// Holding detail: a 560 px drawer at ≥ 1280 px, a full page below
// (nafa.css). Price, position and lots, confidence breakdown, Sharia card,
// orders and fills, and Model vs Account.

import { useEffect, useMemo, useState } from 'react';
import { useHistory, useHoldingDetail, useRoundTrips } from '@/api/client';
import { useConsole, useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { control } from '@/domain/actions';
import { selectConf, selectDrawer, selectPrice, selectShariaCard } from '@/domain/holdings';
import { cx } from '@/lib/format';
import { PriceChart } from '@/components/charts/PriceChart';
import { Icon } from '@/components/icons';
import { Chip, Fresh, Grade, Lifecycle, MicroBar, Note, RatioGauge, Seg, Sk, Spark } from '@/components/ui';

export function HoldingDrawer({ sym }: { sym: string }) {
  const ctx = useCtx();
  const { positions, intents, closeDrawer, dispatch, showToast } = useConsole();
  const detail = useHoldingDetail(sym);
  const hist = useHistory();
  const rt = useRoundTrips();
  const [book, setBook] = useState<'model' | 'account'>('model');
  const h = positions.find((x) => x.symbol === sym);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeDrawer(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [closeDrawer]);
  useEffect(() => setBook('model'), [sym]);

  const dr = useMemo(() => (h ? selectDrawer(ctx, h, positions, intents, hist.data?.orders ?? [], book, detail.data?.lots) : null), [ctx, h, positions, intents, hist.data, book, detail.data]);
  if (ctx.data === 'loading' || ctx.data === 'empty') return null;
  if (!h || !dr) {
    return (
      <>
        <button type="button" className="dscrim" onClick={closeDrawer} aria-label="Close holding detail" tabIndex={-1} />
        <aside className="drawer" aria-label="Holding detail">
          <div className="dh"><div className="row"><span className="sym" style={{ fontSize: 20 }}>{sym}</span><span className="sp" /><button type="button" className="btn ghost icon" onClick={closeDrawer} aria-label="Close"><Icon name="close" /></button></div></div>
          <div className="db"><Note>{sym} is not in the current book.</Note></div>
        </aside>
      </>
    );
  }
  const fr = selectFresh(ctx);
  const sh = selectShariaCard(ctx, h);
  const cf = selectConf(ctx, h, rt.data?.trips ?? [], detail.data?.confidenceHistory ?? []);
  const owner = ctx.role === 'owner';
  const acct = ctx.env !== 'ghost';

  return (
    <>
      <button type="button" className="dscrim" onClick={closeDrawer} aria-label="Close holding detail" tabIndex={-1} />
      <aside className="drawer" aria-label={'Holding detail · ' + h.symbol}>
        <div className="dh">
          <div className="row" style={{ gap: 10, alignItems: 'flex-start' }}>
            <button type="button" className="btn ghost icon mback" onClick={closeDrawer} aria-label="Back"><Icon name="back" /></button>
            <div className="col gap4 sp" style={{ minWidth: 0 }}>
              <div className="row" style={{ gap: 8 }}>
                <span className="sym" style={{ fontSize: 20 }}>{dr.s}</span>
                <Grade g={dr.g} gCls={dr.gCls} />
                <span className={cx('conf', dr.band)}><span className="conf-n">{dr.c}</span><span className="conf-b">{dr.bandL}</span></span>
                {dr.locked && <Chip cls="warn">Locked</Chip>}
                {dr.forced && <Chip cls="danger">Exit queued</Chip>}
              </div>
              <span className="xs muted">{dr.n} · {dr.sec} · {dr.ind}</span>
            </div>
            <button type="button" className="btn ghost icon wide-only" onClick={closeDrawer} aria-label="Close"><Icon name="close" /></button>
          </div>
          <div className="row wrap" style={{ gap: 12, alignItems: 'flex-end' }}>
            <div className="col gap4">
              <span className={cx('bigpnl', dr.uCls)}>{dr.u}</span>
              <span className="sm"><span className={dr.uCls}>{dr.uP}</span><span className="dim"> unrealized · {dr.val} · {dr.w} of equity</span></span>
            </div>
            <span className="sp" />
            <Seg label="Book" value={dr.isA ? 'account' : 'model'} onChange={(b) => (b === 'account' && !acct ? showToast('No broker account in Ghost — it starts Mon 2 Nov') : setBook(b))} items={[{ k: 'model', l: 'Model' }, { k: 'account', l: 'Account' }]} />
          </div>
          {owner && (
            <div className="row wrap" style={{ gap: 8 }}>
              <button type="button" className="btn sm" onClick={() => dispatch(control(dr.locked ? 'unlock' : 'lock', h.symbol))}><Icon name="lock" className="s14" />{dr.locked ? 'Unlock' : 'Lock'}</button>
              <button type="button" className="btn sm" onClick={() => dispatch(control('trim', h.symbol))} disabled={dr.forced}>Trim…</button>
              <button type="button" className="btn sm danger-o" onClick={() => dispatch(control('force_exit', h.symbol))} disabled={dr.forced}>Force exit…</button>
              <span className="eff">Effective: tonight’s 19:15 ET submit</span>
            </div>
          )}
        </div>

        <div className="db">
          <section className="dsec">
            <div className="row"><h4>Price · 70 sessions</h4><span className="sp" /><Fresh cls={fr.model.cls} l={fr.model.s} /></div>
            <div className="legend xs">
              <span><i className="sw model" />close</span>
              <span><i className="sw" style={{ background: 'var(--info)' }} />SMA50</span>
              <span><i className="sw" style={{ background: 'var(--acct)' }} />SMA200</span>
              <span><span className="mk buy" style={{ position: 'static', transform: 'none' }}>B</span>fill</span>
            </div>
            {detail.data ? <PriceChart v={selectPrice(h, detail.data)} /> : <Sk h={210} />}
          </section>

          <section className="dsec">
            <h4>Position</h4>
            <dl className="kv" style={{ margin: 0 }}>
              <dt>Shares · avg cost</dt><dd>{dr.sh} @ {dr.avg}</dd>
              <dt>Last</dt><dd>{dr.last} <span className={dr.dayCls}>{dr.day}</span></dd>
              <dt>Value · weight</dt><dd>{dr.val} · {dr.w}</dd>
              <dt>Cap headroom</dt><dd>{dr.cap}</dd>
              <dt>Entry</dt><dd>{dr.ed}</dd>
              <dt>Entry reason</dt><dd className="dim" style={{ whiteSpace: 'normal' }}>“{dr.why}”</dd>
              <dt>Time stop</dt><dd>{dr.ts}</dd>
              <dt>Nearest exit</dt><dd className={dr.exCls}>{dr.ex}</dd>
              <dt>Realized on this name</dt><dd>$0.00</dd>
            </dl>
            <div className="col gap4"><span className="up">Lots · FIFO</span>
              <div className="dt dense" style={{ minWidth: 0 }}>
                <div className="dt-r dt-h" style={{ gridTemplateColumns: '1fr 64px 84px 96px 96px' }}><span>Opened</span><span className="r">Shares</span><span className="r">Cost</span><span className="r">Value</span><span className="r">Unrealized</span></div>
                {dr.lots.map((l) => (
                  <div key={l.d} className="dt-r" style={{ gridTemplateColumns: '1fr 64px 84px 96px 96px' }}><span className="num">{l.d}</span><span className="r num">{l.q}</span><span className="r num">{l.c}</span><span className="r num">{l.v}</span><span className={cx('r num', l.cls)}>{l.u}</span></div>
                ))}
              </div>
            </div>
          </section>

          <section className="dsec">
            <div className="row"><h4>Confidence</h4><span className="sp" /><span className="xs it">Model conviction, not a forecast.</span></div>
            <div className="row" style={{ gap: 14, alignItems: 'center' }}>
              <span className="num" style={{ fontSize: 34, fontWeight: 750, lineHeight: 1 }}>{cf.tot}</span>
              <div className="col gap4" style={{ minWidth: 0 }}>
                <Chip cls={cf.chip} style={{ alignSelf: 'flex-start' }}>{cf.bandL} band</Chip>
                <span className="xs muted">at entry {cf.c0} · 40% Signal · 30% Risk room · 20% Regime · 10% Data</span>
              </div>
              <span className="sp" />
              <div className="col gap4 wide-only" style={{ width: 120, flex: 'none' }}>
                <Spark d={cf.spark} box="0 0 100 30" style={{ width: 120, height: 32, overflow: 'visible' }} />
                <span className="xs muted">over {cf.n} sessions</span>
              </div>
            </div>
            <MicroBar segs={cf.segs} className={cx('lg', cf.band)} />
            <div className="col" style={{ gap: 11 }}>
              {cf.subs.map((s) => (
                <div key={s.n} className="col gap4">
                  <div className="row">
                    <span className="b sm" style={{ width: 78, flex: 'none' }}>{s.n}</span>
                    <span className="xs muted" style={{ width: 30, flex: 'none' }}>{s.w}</span>
                    <span className="bar sp" style={{ height: 5 }}><i className={cx('bar-f', s.cls)} style={{ width: s.v + '%' }} /></span>
                    <span className="num b" style={{ width: 28, textAlign: 'right', flex: 'none' }}>{s.v}</span>
                  </div>
                  <span className="xs dim">{s.why}</span>
                </div>
              ))}
            </div>
            <Note>{cf.cal}</Note>
          </section>

          <section className="dsec">
            <div className="row"><h4>Sharia</h4><span className="sp" /><Chip cls="warn">Unlicensed proxy · yfinance</Chip></div>
            <div className="row" style={{ gap: 14 }}>
              <Grade g={sh.g} gCls={sh.gCls} xl />
              <div className="col gap4"><Chip cls={sh.stCls} style={{ alignSelf: 'flex-start' }}>{sh.status}</Chip><span className="xs muted">{sh.why}</span></div>
            </div>
            <RatioGauge label="Debt / market cap" r={sh.debt} />
            <RatioGauge label="Cash / market cap" r={sh.cash} />
            <ShariaKv sh={sh} />
          </section>

          <section className="dsec">
            <h4>Orders &amp; fills</h4>
            {dr.ords.map((o, i) => (
              <div key={i} className="col" style={{ gap: 8, padding: '10px 12px', border: '1px solid var(--line-1)', borderRadius: 8, background: 'var(--bg-2)' }}>
                <div className="row"><span className={cx('side', o.sideCls)}>{o.side}</span><span className="num sm b">{o.q}</span><span className="xs muted">{o.when}</span><span className="sp" /><span className="num sm">{o.px}</span></div>
                <Lifecycle steps={o.lc} minWidth={74} />
                <span className="xs dim">{o.why}</span>
              </div>
            ))}
            {!dr.ords.length && <span className="sm muted">No orders on this name since the twin started.</span>}
          </section>

          <section className="dsec">
            <h4>Model vs account</h4>
            {dr.acctOk ? (
              <>
                <div className="dt dense" style={{ minWidth: 0 }}>
                  <div className="dt-r dt-h" style={{ gridTemplateColumns: '1fr 100px 100px 90px' }}><span /><span className="r">Model</span><span className="r acct">Account</span><span className="r">Δ</span></div>
                  {dr.cmp.map((r) => (
                    <div key={r.k} className="dt-r" style={{ gridTemplateColumns: '1fr 100px 100px 90px' }}><span className="dim">{r.k}</span><span className="r num">{r.m}</span><span className="r num">{r.a}</span><span className={cx('r num', r.cls)}>{r.d}</span></div>
                  ))}
                </div>
                <Note tone={dr.driftCls === 'warn' ? 'warn' : 'ok'}>{dr.drift}</Note>
              </>
            ) : (
              <p className="sm muted">No broker account in Ghost — the account book starts in cash on Mon 2 Nov.</p>
            )}
          </section>
        </div>
      </aside>
    </>
  );
}

export function ShariaKv({ sh }: { sh: ReturnType<typeof selectShariaCard> }) {
  return (
    <dl className="kv" style={{ margin: 0 }}>
      <dt>Impermissible income</dt><dd className="it">Not available – licensed data pending</dd>
      <dt>Business activity</dt><dd className={sh.bizCls} style={{ whiteSpace: 'normal' }}>{sh.biz}</dd>
      <dt>Instrument</dt><dd>Common share <span className="pos">✓</span></dd>
      <dt>Review flag</dt><dd className={sh.flagCls}>{sh.flag}</dd>
      <dt>Owner ruling</dt><dd>{sh.ruling}</dd>
      <dt>Screened</dt><dd>{sh.screened}</dd>
      <dt>Purification</dt><dd style={{ whiteSpace: 'normal' }}>{sh.purif}</dd>
    </dl>
  );
}
