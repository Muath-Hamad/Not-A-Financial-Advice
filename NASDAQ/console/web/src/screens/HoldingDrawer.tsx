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
import { wdLabel } from '@/lib/dates';
import { PriceChart } from '@/components/charts/PriceChart';
import { Icon } from '@/components/icons';
import { Chip, Fresh, Grade, Lifecycle, MicroBar, Note, RatioGauge, Seg, Sk, Spark } from '@/components/ui';
import { Gloss, T } from '@/glossary/Term';
import type { TermKey } from '@/glossary/terms';

const SUB_TERMS: TermKey[] = ['signal', 'riskRoom', 'regimeScore', 'dataScore'];

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
  const cf = selectConf(ctx, h, rt.data?.trips ?? [], detail.data?.confidenceHistory ?? [], detail.data?.calibration ?? []);
  const price = detail.data ? selectPrice(h, detail.data) : null;
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
                {dr.band === 'none'
                  ? <span className="conf"><span className="conf-n muted">—</span><span className="conf-b muted"><T k="confidence">Pending</T></span></span>
                  : <span className={cx('conf', dr.band)}><span className="conf-n">{dr.c}</span><span className="conf-b">{dr.bandL}</span></span>}
                {dr.locked && <Chip cls="warn"><T k="locked">Locked</T></Chip>}
                {dr.forced && <Chip cls="danger">Exit queued</Chip>}
              </div>
              <span className="xs muted">{dr.n} · {dr.sec} · {dr.ind}</span>
            </div>
            <button type="button" className="btn ghost icon wide-only" onClick={closeDrawer} aria-label="Close"><Icon name="close" /></button>
          </div>
          <div className="row wrap" style={{ gap: 12, alignItems: 'flex-end' }}>
            <div className="col gap4">
              <span className={cx('bigpnl', dr.uCls)}>{dr.u}</span>
              <span className="sm"><span className={dr.uCls}>{dr.uP}</span><span className="dim"> <T k="unrealized">unrealized</T> · {dr.val} · {dr.w} of <T k="equity">equity</T></span></span>
            </div>
            <span className="sp" />
            <Seg label="Book" value={dr.isA ? 'account' : 'model'} onChange={(b) => (b === 'account' && !acct ? showToast('No broker account in Ghost — it starts ' + wdLabel(ctx.facts.paperStart)) : setBook(b))} items={[{ k: 'model', l: 'Model' }, { k: 'account', l: 'Account' }]} />
          </div>
          {owner && (
            <div className="row wrap" style={{ gap: 8 }}>
              <button type="button" className="btn sm" onClick={() => dispatch(control(dr.locked ? 'unlock' : 'lock', h.symbol))}><Icon name="lock" className="s14" />{dr.locked ? 'Unlock' : 'Lock'}</button>
              <button type="button" className="btn sm" onClick={() => dispatch(control('trim', h.symbol))} disabled={dr.forced}>Trim…</button>
              <button type="button" className="btn sm danger-o" onClick={() => dispatch(control('force_exit', h.symbol))} disabled={dr.forced}>Force exit…</button>
              <span className="eff">Effective: tonight’s 19:15 ET <T k="submit">submit</T></span>
            </div>
          )}
        </div>

        <div className="db">
          <section className="dsec">
            <div className="row"><h4>Price · 70 <T k="session">sessions</T></h4><span className="sp" /><Fresh cls={fr.model.cls} l={fr.model.s} /></div>
            {price && (
              <div className="legend xs">
                <span><i className="sw model" />close</span>
                <span><i className="sw" style={{ background: 'var(--info)' }} /><T k="sma">SMA50</T></span>
                <span><i className="sw" style={{ background: 'var(--acct)' }} /><T k="sma">SMA200</T></span>
                <span><span className="mk buy" style={{ position: 'static', transform: 'none' }}>B</span>fill</span>
              </div>
            )}
            {!detail.data ? <Sk h={210} /> : price ? <PriceChart v={price} /> : <Note>{detail.data.pricesNote ?? 'No price history for this holding yet.'}</Note>}
          </section>

          <section className="dsec">
            <h4>Position</h4>
            <dl className="kv" style={{ margin: 0 }}>
              <dt><T k="shares">Shares</T> · <T k="avgCost">avg cost</T></dt><dd>{dr.sh} @ {dr.avg}</dd>
              <dt><T k="last">Last</T></dt><dd>{dr.last} <span className={dr.dayCls}>{dr.day}</span></dd>
              <dt><T k="value">Value</T> · <T k="weight">weight</T></dt><dd>{dr.val} · {dr.w}</dd>
              <dt><T k="posCap">Cap headroom</T></dt><dd>{dr.cap}</dd>
              <dt>Entry</dt><dd>{dr.ed}</dd>
              <dt>Entry reason</dt><dd className="dim" style={{ whiteSpace: 'normal' }}>“<Gloss text={dr.why} />”</dd>
              <dt><T k="timeStop">Time stop</T></dt><dd>{dr.ts}</dd>
              <dt><T k="nearestExit">Nearest exit</T></dt><dd className={dr.exCls} style={{ whiteSpace: 'normal' }}><Gloss text={dr.ex} /></dd>
              <dt><T k="realized">Realized on this name</T></dt><dd>$0.00</dd>
            </dl>
            <div className="col gap4"><span className="up"><T k="fifo">Lots · FIFO</T></span>
              <div className="dt dense" style={{ minWidth: 0 }}>
                <div className="dt-r dt-h" style={{ gridTemplateColumns: '1fr 64px 84px 96px 96px' }}><span>Opened</span><span className="r">Shares</span><span className="r">Cost</span><span className="r">Value</span><span className="r">Unrealized</span></div>
                {dr.lots.map((l) => (
                  <div key={l.d} className="dt-r" style={{ gridTemplateColumns: '1fr 64px 84px 96px 96px' }}><span className="num">{l.d}</span><span className="r num">{l.q}</span><span className="r num">{l.c}</span><span className="r num">{l.v}</span><span className={cx('r num', l.cls)}>{l.u}</span></div>
                ))}
              </div>
            </div>
          </section>

          <section className="dsec">
            <div className="row"><h4><T k="confidence">Confidence</T></h4><span className="sp" /><span className="xs it">Model conviction, not a forecast.</span></div>
            {cf ? (
              <>
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
                  {cf.subs.map((s, i) => (
                    <div key={s.n} className="col gap4">
                      <div className="row">
                        <span className="b sm" style={{ width: 78, flex: 'none' }}><T k={SUB_TERMS[i]}>{s.n}</T></span>
                        <span className="xs muted" style={{ width: 30, flex: 'none' }}>{s.w}</span>
                        <span className="bar sp" style={{ height: 5 }}><i className={cx('bar-f', s.cls)} style={{ width: s.v + '%' }} /></span>
                        <span className="num b" style={{ width: 28, textAlign: 'right', flex: 'none' }}>{s.v}</span>
                      </div>
                      <span className="xs dim"><Gloss text={s.why} /></span>
                    </div>
                  ))}
                </div>
                <Note>{cf.cal}</Note>
              </>
            ) : (
              <Note>
                Not available yet. Confidence ratings — <T k="signal">Signal</T>, <T k="riskRoom">Risk room</T>, <T k="regimeScore">Regime</T> and <T k="dataScore">Data</T> — and the stop levels are written by
                the insights step that runs after Cycle A (milestone M3). Nothing is estimated in the meantime.
              </Note>
            )}
          </section>

          <section className="dsec">
            <div className="row"><h4><T k="shariaGrade">Sharia</T></h4><span className="sp" /><Chip cls="warn"><T k="unlicensed">Unlicensed proxy · yfinance</T></Chip></div>
            <div className="row" style={{ gap: 14 }}>
              <Grade g={sh.g} gCls={sh.gCls} xl />
              <div className="col gap4"><Chip cls={sh.stCls} style={{ alignSelf: 'flex-start' }}>{sh.status}</Chip><span className="xs muted"><Gloss text={sh.why} /></span></div>
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
                <span className="xs dim"><Gloss text={o.why} /></span>
              </div>
            ))}
            {!dr.ords.length && <span className="sm muted">No orders on this name since the twin started.</span>}
          </section>

          <section className="dsec">
            <h4><T k="model">Model</T> vs <T k="account">account</T></h4>
            {dr.acctOk ? (
              <>
                <div className="dt dense" style={{ minWidth: 0 }}>
                  <div className="dt-r dt-h" style={{ gridTemplateColumns: '1fr 100px 100px 90px' }}><span /><span className="r">Model</span><span className="r acct">Account</span><span className="r">Δ</span></div>
                  {dr.cmp.map((r) => (
                    <div key={r.k} className="dt-r" style={{ gridTemplateColumns: '1fr 100px 100px 90px' }}><span className="dim">{r.k}</span><span className="r num">{r.m}</span><span className="r num">{r.a}</span><span className={cx('r num', r.cls)}>{r.d}</span></div>
                  ))}
                </div>
                <Note tone={dr.driftCls === 'warn' ? 'warn' : 'ok'}><Gloss text={dr.drift} /></Note>
              </>
            ) : (
              <p className="sm muted">No broker account in <T k="ghost">Ghost</T> — the account book starts in cash on {wdLabel(ctx.facts.paperStart)}.</p>
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
      <dt><T k="impermissible">Impermissible income</T></dt><dd className="it">Not available – licensed data pending</dd>
      <dt><T k="businessActivity">Business activity</T></dt><dd className={sh.bizCls} style={{ whiteSpace: 'normal' }}>{sh.biz}</dd>
      <dt>Instrument</dt><dd><T k="commonShare">Common share</T> <span className="pos">✓</span></dd>
      <dt><T k="reviewFlag">Review flag</T></dt><dd className={sh.flagCls}>{sh.flag}</dd>
      <dt><T k="ruling">Owner ruling</T></dt><dd>{sh.ruling}</dd>
      <dt><T k="rescreen">Screened</T></dt><dd>{sh.screened}</dd>
      <dt><T k="purification">Purification</T></dt><dd style={{ whiteSpace: 'normal' }}>{sh.purif}</dd>
    </dl>
  );
}
