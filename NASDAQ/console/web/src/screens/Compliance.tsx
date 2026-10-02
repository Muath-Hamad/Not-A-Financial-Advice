import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useCompliance } from '@/api/client';
import { useConsole, useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { selectCards, selectRescreen, selectUniverse, type UniFilter } from '@/domain/compliance';
import { selectCompStrip } from '@/domain/overview';
import { cx } from '@/lib/format';
import { Chip, Grade, Note, PageHeader, Panel, RatioGauge, Seg, Sk, StackBar, Stat, Tabs } from '@/components/ui';
import { ShariaKv } from './HoldingDrawer';
import { exportCsv } from './csv';

type Tab = 'holdings' | 'universe' | 'rescreen' | 'purif';

export function Compliance() {
  const { tab = 'holdings' } = useParams();
  const navigate = useNavigate();
  const t = (['holdings', 'universe', 'rescreen', 'purif'].includes(tab) ? tab : 'holdings') as Tab;
  const ctx = useCtx();
  const { positions } = useConsole();
  const cq = useCompliance();
  const cs = selectCompStrip(ctx, positions, cq.data?.universe ?? []);
  return (
    <div className="page">
      <PageHeader title="Compliance" sub="AAOIFI SS 21 screen · 319-name frozen universe · debt and cash vs market cap below 30% · business activity · common shares only">
        <span className="sp" /><Chip cls="warn">Data: unlicensed proxy (yfinance) · licensed feed in R3</Chip>
      </PageHeader>
      <div className="g4">
        <div className="statbox"><span className="l">Book by grade</span><StackBar segs={cs.stack} style={{ margin: '6px 0 4px' }} /><span className="xs muted">{cs.stackL}</span></div>
        <Stat l="Held names under review" v={cs.rev} vCls="warn" s="ruling due Fri 30 Oct (D1)" />
        <Stat l="Watchlist · within 3 pp" v={cs.watch} s="none held" />
        <Stat l="Last / next re-screen" v="Thu 1 Oct → Fri 1 Jan" vStyle={{ fontSize: 14 }} s="0 held names affected on 1 Oct" />
      </div>
      <Tabs<Tab> value={t} onChange={(k) => navigate('/compliance/' + k)} items={[{ k: 'holdings', l: 'Holdings' }, { k: 'universe', l: 'Universe & watchlist' }, { k: 'rescreen', l: 'Re-screens' }, { k: 'purif', l: 'Purification' }]} />
      {t === 'holdings' && <Cards />}
      {t === 'universe' && <Universe />}
      {t === 'rescreen' && <Rescreens />}
      {t === 'purif' && <Purification />}
    </div>
  );
}

function Cards() {
  const ctx = useCtx();
  const { positions, openDrawer } = useConsole();
  return (
    <div className="cards">
      {selectCards(ctx, positions).map((c) => (
        <article key={c.s} className="hcard">
          <div className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
            <div className="col gap4 sp">
              <button type="button" className="linkbtn" onClick={() => openDrawer(c.s)}><span className="sym lg">{c.s}</span></button>
              <span className="xs muted">{c.n} · {c.w} of book</span>
              <Chip cls={c.stCls} style={{ alignSelf: 'flex-start' }}>{c.status}</Chip>
            </div>
            <Grade g={c.g} gCls={c.gCls} xl />
          </div>
          <RatioGauge label="Debt / market cap" r={c.debt} />
          <RatioGauge label="Cash / market cap" r={c.cash} />
          <ShariaKv sh={c} />
          <div className="row"><Chip cls="warn">Unlicensed proxy · yfinance</Chip><span className="sp" /><span className="xs muted">grade per docs/08 §5</span></div>
        </article>
      ))}
    </div>
  );
}

const UNI_COLS = '80px minmax(190px, 1fr) 160px 70px 150px 150px minmax(220px, 1.4fr) 70px';

function Universe() {
  const ctx = useCtx();
  const { positions } = useConsole();
  const cq = useCompliance();
  const [f, setF] = useState<UniFilter>('all');
  if (!cq.data) return <Panel><div className="pb"><Sk h={300} /></div></Panel>;
  const u = selectUniverse(ctx, positions, cq.data, f);
  const onExport = () => exportCsv('universe_' + cq.data!.screenedOn + '.csv', ['Symbol', 'Name', 'Status', 'Grade', 'Debt/mcap', 'Cash/mcap', 'Flag', 'Held'], u.rows.map((r) => [r.s, r.n, r.st, r.g, r.d, r.c, r.flag, r.held]));
  return (
    <>
      <div className="row wrap" style={{ gap: 8 }}>
        <Seg<UniFilter> label="Universe filter" value={f} onChange={setF} items={[{ k: 'all', l: 'All' }, { k: 'watch', l: 'Watchlist' }, { k: 'review', l: 'Under review' }, { k: 'excl', l: 'Excluded' }, { k: 'held', l: 'Held' }]} />
        <span className="sp" /><span className="xs muted">Universe frozen for the evaluation — rulings act only through exclusions and forced exits</span>
      </div>
      <Panel title="Universe" hint={u.hint} fresh={{ l: 'screened Thu 1 Oct 10:00 ET' }} footer={<><span>{u.foot}</span><span className="sp" /><button type="button" className="btn sm" onClick={onExport}>Export universe CSV</button></>}>
        <div className="twrap">
          <div className="dt flush">
            <div className="dt-r dt-h" style={{ gridTemplateColumns: UNI_COLS }}><span>Symbol</span><span>Name</span><span>Status</span><span>Grade</span><span>Debt headroom</span><span>Cash headroom</span><span>Review flag / note</span><span>Held</span></div>
            {u.rows.map((r) => (
              <div key={r.s} className="dt-r" style={{ gridTemplateColumns: UNI_COLS }}>
                <span className="sym">{r.s}</span><span className="dim">{r.n}</span><span><Chip cls={r.stCls}>{r.st}</Chip></span><span><Grade g={r.g} gCls={r.gCls} /></span>
                <span className="num"><span className={r.dCls}>{r.dh}</span> <span className="xs muted">({r.d})</span></span>
                <span className="num"><span className={r.cCls}>{r.ch}</span> <span className="xs muted">({r.c})</span></span>
                <span className="xs dim wc">{r.flag}</span><span>{r.held}</span>
              </div>
            ))}
          </div>
        </div>
      </Panel>
    </>
  );
}

function Rescreens() {
  const cq = useCompliance();
  const [sel, setSel] = useState('q4');
  if (!cq.data) return <Panel><div className="pb"><Sk h={300} /></div></Panel>;
  const rs = selectRescreen(cq.data, sel);
  return (
    <div className="g12">
      <Panel className="c4" title="Re-screen timeline">
        <div className="pb col" style={{ gap: 0 }}>
          {rs.list.map((r) => (
            <button key={r.id} type="button" className="linkbtn row" style={{ alignItems: 'flex-start', gap: 12, padding: '10px 8px', borderRadius: 6, background: r.on ? 'var(--bg-3)' : 'transparent' }} onClick={() => setSel(r.id)} aria-pressed={r.on}>
              <span className={cx('dot', r.dot)} style={{ marginTop: 5 }} />
              <span className="col gap4" style={{ minWidth: 0 }}><span className="b">{r.d}</span><span className="xs muted">{r.k}</span><span className="xs dim">{r.sum}</span></span>
            </button>
          ))}
          <div className="row xs muted" style={{ padding: '10px 8px', gap: 12 }}><span className="dot off" />Next: Fri 1 Jan 2027 10:00 ET (rescreen step)</div>
        </div>
      </Panel>
      <Panel className="c8" title={rs.sel.d} hint={rs.sel.k} fresh={{ l: 'compliance/' + rs.sel.file + '.json' }}>
        <div className="pb col" style={{ gap: 14 }}>
          <div className="g4">{rs.sel.stats.map((x) => <Stat key={x.l} l={x.l} v={x.v} vCls={x.cls} />)}</div>
          <div className="col gap4">
            <span className="up">{rs.sel.h1}</span>
            <div className="olist">{rs.sel.out.map((o) => <div key={o.s} className="oitem"><span className="sym">{o.s}</span><span className="dim">{o.r}</span><span className={cx('tag chip', o.cls)}>{o.t}</span></div>)}</div>
          </div>
          {(rs.sel.h2 || rs.sel.note2) && (
            <div className="col gap4">
              <span className="up">{rs.sel.h2}</span>
              <div className="row wrap" style={{ gap: 6 }}>{rs.sel.inn.map((s) => <Chip key={s}>{s}</Chip>)}</div>
              <span className="xs muted">{rs.sel.note2}</span>
            </div>
          )}
          <Note tone={rs.sel.noteCls}>{rs.sel.note}</Note>
        </div>
      </Panel>
    </div>
  );
}

const DIV_COLS = '120px 70px 64px 84px 96px 84px 190px 150px 90px';

function Purification() {
  const ctx = useCtx();
  const fr = selectFresh(ctx);
  return (
    <div className="g12">
      <Panel className="c8" title="Dividend ledger" hint="purification = dividend × impermissible-income %" fresh={fr.acct}
        footer={<span>2026 totals · gross <b className="num">$0.00</b> · withholding <b className="num">$0.00</b> · net <b className="num">$0.00</b> · to purify <span className="it">rate pending</span></span>}>
        <div className="twrap">
          <div className="dt flush">
            <div className="dt-r dt-h" style={{ gridTemplateColumns: DIV_COLS }}><span>Pay date</span><span>Symbol</span><span className="r">Shares</span><span className="r">Gross</span><span className="r">Withholding</span><span className="r">Net</span><span>Impermissible %</span><span>To purify</span><span>Paid?</span></div>
            <div className="dt-r" style={{ gridTemplateColumns: DIV_COLS }}>
              <span className="num">Tue 20 Oct <span className="xs muted">proj.</span></span><span className="sym">MU</span><span className="r num">6</span><span className="r num">$0.69</span><span className="r num">−$0.21</span><span className="r num">$0.48</span>
              <span className="it wc">Not available – licensed data pending</span><span className="it">rate pending</span><span><Chip>Projected</Chip></span>
            </div>
            <div className="dt-r mut" style={{ gridTemplateColumns: DIV_COLS }}><span className="wc" style={{ gridColumn: '1 / -1', padding: '12px 14px' }}>No dividends received since the twin started on Tue 18 Aug. The other nine holdings pay none.</span></div>
          </div>
        </div>
      </Panel>
      <Panel className="c4" title="Zakat estimate" extra={<Chip style={{ marginLeft: 'auto' }}>Planned – Phase 5</Chip>}>
        <div className="pb col" style={{ gap: 10 }}>
          <p className="sm dim">A yearly zakat statement arrives with the licensed Sharia data (task R3) and the real-money account. Paper and ghost balances are not zakatable wealth.</p>
          <dl className="kv" style={{ margin: 0 }}><dt>Method</dt><dd className="it">to be set in the written policy (D1)</dd><dt>Basis</dt><dd className="it">zakatable assets per share — vendor data</dd><dt>First statement</dt><dd>after the first lunar year of the pilot</dd></dl>
        </div>
      </Panel>
    </div>
  );
}
