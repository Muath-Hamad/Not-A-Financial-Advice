import { Fragment, useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable, type VisibilityState } from '@tanstack/react-table';
import { useConsole, useCtx } from '@/app/console';
import { selectFresh } from '@/domain/chrome';
import { control, nav } from '@/domain/actions';
import type { HoldingRow } from '@/domain/core';
import { NO_FILTERS, selectHoldings, selectSide, type Book, type HoldingsFilters } from '@/domain/holdings';
import { cx } from '@/lib/format';
import { Icon } from '@/components/icons';
import { BookTag, Chip, Conf, Empty, ExportButton, Fresh, Note, PageHeader, Seg, Shar } from '@/components/ui';
import { HoldingCard, WeightCell } from './Overview';
import { exportCsv } from './csv';

const col = createColumnHelper<HoldingRow>();

interface ColMeta {
  w: string;
  cls?: string;
  head?: string;
  stick?: boolean;
}

export function Holdings() {
  const ctx = useCtx();
  const { positions, intents, openDrawer, dispatch, drawer } = useConsole();
  const [sp, setSp] = useSearchParams();
  const book = (['model', 'account', 'side'].includes(sp.get('book') || '') ? sp.get('book') : 'model') as Book;
  const setBook = (b: Book) => {
    const n = new URLSearchParams(sp);
    if (b === 'model') n.delete('book'); else n.set('book', b);
    setSp(n);
    setMenu(null);
  };
  const [fl, setFl] = useState<HoldingsFilters>(NO_FILTERS);
  const [vis, setVis] = useState<VisibilityState>({ realized: true, held: true, pending: true });
  const [colMenu, setColMenu] = useState(false);
  const [menu, setMenu] = useState<string | null>(null);
  const owner = ctx.role === 'owner';
  const fr = selectFresh(ctx);
  const hd = useMemo(
    () => selectHoldings(ctx, positions, intents, book, fl, { realized: vis.realized !== false, held: vis.held !== false, pending: vis.pending !== false }, fr.model),
    [ctx, positions, intents, book, fl, vis, fr.model],
  );
  const set = (p: Partial<HoldingsFilters>) => setFl((x) => ({ ...x, ...p }));

  const columns = useMemo(() => [
    col.display({ id: 'symbol', meta: { w: '170px', stick: true, head: 'Symbol' } as ColMeta, cell: ({ row: { original: h } }) => (
      <button type="button" className="linkbtn" onClick={() => openDrawer(h.s)}>
        <span className="row gap4"><span className="sym">{h.s}</span>{h.locked && <Icon name="lock" className="s14 warn" />}</span>
        <span className="symname">{h.n} · {h.sec}</span>
      </button>
    ) }),
    col.accessor('sh', { meta: { w: '64px', cls: 'r num', head: 'Shares' } as ColMeta }),
    col.accessor('avg', { meta: { w: '84px', cls: 'r num', head: 'Avg cost' } as ColMeta }),
    col.display({ id: 'last', meta: { w: '88px', cls: 'r', head: 'Last' } as ColMeta, cell: ({ row: { original: h } }) => <><span className="num">{h.last}</span><span className={cx('xs', h.dayCls)} style={{ display: 'block' }}>{h.day}</span></> }),
    col.accessor('val', { meta: { w: '96px', cls: 'r num', head: 'Value' } as ColMeta }),
    col.display({ id: 'weight', meta: { w: '140px', head: 'Weight · cap 18%' } as ColMeta, cell: ({ row: { original: h } }) => <WeightCell h={h} /> }),
    col.display({ id: 'unrealized', meta: { w: '112px', cls: 'r', head: 'Unrealized' } as ColMeta, cell: ({ row: { original: h } }) => <><span className={cx('num', h.uCls)}>{h.u}</span><span className={cx('xs', h.uCls)} style={{ display: 'block' }}>{h.uP}</span></> }),
    col.accessor('rz', { id: 'realized', meta: { w: '84px', cls: 'r num muted', head: 'Realized' } as ColMeta }),
    col.display({ id: 'held', meta: { w: '120px', head: 'Held / 35' } as ColMeta, cell: ({ row: { original: h } }) => (
      <span className="held"><span className="num xs" style={{ width: 40 }}>{h.held}</span><span className="bar"><i className={cx('bar-f', h.heldCls)} style={{ width: h.heldB + '%' }} /></span></span>
    ) }),
    col.display({ id: 'exit', meta: { w: '210px', head: 'Nearest exit' } as ColMeta, cell: ({ row: { original: h } }) => <span className={h.exCls}><span className="b">{h.exK}</span> <span className="num">{h.exP}</span><span className="xs" style={{ display: 'block' }}>{h.exD}</span></span> }),
    col.display({ id: 'conf', meta: { w: '150px', head: 'Confidence' } as ColMeta, cell: ({ row: { original: h } }) => <Conf c={h.c} band={h.band} bandL={h.bandL} segs={h.segs} title={h.cT} /> }),
    col.display({ id: 'sharia', meta: { w: '140px', head: 'Sharia' } as ColMeta, cell: ({ row: { original: h } }) => <Shar g={h.g} gCls={h.gCls} stat={h.stat} /> }),
    col.display({ id: 'pending', meta: { w: '180px', head: 'Pending' } as ColMeta, cell: ({ row: { original: h } }) => <span className={cx('xs', h.pCls)}>{h.pend}</span> }),
    col.display({ id: 'menu', meta: { w: '48px', cls: 'c', head: '' } as ColMeta, cell: ({ row: { original: h } }) => owner
      ? <button type="button" className="btn ghost sm icon" onClick={() => setMenu(menu === h.s ? null : h.s)} aria-label={'Overrides for ' + h.s} aria-expanded={menu === h.s} title="Lock · Trim · Force exit">⋯</button>
      : null }),
  ], [openDrawer, owner, menu]);

  const table = useReactTable({ data: hd.rows, columns, state: { columnVisibility: vis }, onColumnVisibilityChange: setVis, getCoreRowModel: getCoreRowModel(), getRowId: (r) => r.s });
  const visible = table.getVisibleLeafColumns();
  const gridCols = visible.map((c) => (c.columnDef.meta as ColMeta).w).join(' ');
  const totals: Record<string, ReactNode> = {
    symbol: 'Total · ' + hd.n + ' positions',
    val: hd.tMV,
    weight: <span className="num">{hd.tW}</span>,
    unrealized: <span className={cx('num', hd.tUCls)}>{hd.tU}</span>,
    realized: <span className={cx('num', hd.tRCls)}>{hd.tR}</span>,
    exit: <span className="dim" style={{ fontWeight: 500 }}>Cash {hd.cash} · Equity <b>{hd.eq}</b></span>,
    conf: <Conf c={hd.tC} band={hd.tBand} bandL="weighted" bar={false} />,
    sharia: <span className="xs muted" style={{ fontWeight: 500 }}>{hd.tGrades}</span>,
  };

  const onExport = () => {
    exportCsv('holdings_' + ctx.asof + '_' + book + '.csv', ['Symbol', 'Name', 'Shares', 'Avg cost', 'Last', 'Value', 'Weight', 'Unrealized', 'Confidence', 'Grade', 'Sharia', 'Nearest exit'],
      hd.rows.map((r) => [r.s, r.n, r.sh, r.avg, r.last, r.val, r.w, r.u, r.c, r.g, r.stat, r.exK + ' ' + r.exP]));
  };

  return (
    <div className="page">
      <PageHeader title="Holdings" sub={hd.sub}>
        <span className="sp" />
        <Seg<Book> label="Book" value={book} onChange={setBook} items={[{ k: 'model', l: 'Model' }, { k: 'account', l: 'Account' }, { k: 'side', l: 'Side-by-side' }]} />
        <ExportButton onClick={onExport} wideOnly />
      </PageHeader>

      <div className="row wrap" style={{ gap: 8 }}>
        <label className="search-w"><Icon name="search" /><input className="inp search" placeholder="Search symbol or name" value={fl.q} onChange={(e) => set({ q: e.target.value })} aria-label="Search holdings" /></label>
        <select className="sel" value={fl.sector} onChange={(e) => set({ sector: e.target.value })} aria-label="Sector">
          <option value="all">All sectors</option>
          {hd.sectors.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select className="sel" value={fl.grade} onChange={(e) => set({ grade: e.target.value })} aria-label="Sharia grade">
          <option value="all">All grades</option><option value="A">Grade A</option><option value="B">Grade B</option><option value="C">Grade C</option><option value="F">Grade F</option>
        </select>
        <select className="sel" value={fl.band} onChange={(e) => set({ band: e.target.value })} aria-label="Confidence band">
          <option value="all">All confidence</option><option value="high">High ≥ 70</option><option value="med">Medium 40–69</option><option value="low">Low &lt; 40</option>
        </select>
        <Seg label="P&L sign" value={fl.sign} onChange={(sign) => set({ sign })} items={[{ k: 'all', l: 'All' }, { k: 'pos', l: '+ P&L' }, { k: 'neg', l: '− P&L' }]} />
        <button type="button" className={cx('chip', fl.near && 'warn')} style={{ height: 30, cursor: 'pointer' }} onClick={() => set({ near: !fl.near })} aria-pressed={fl.near}>
          {fl.near ? 'Near an exit trigger ✓' : 'Near an exit trigger'}
        </button>
        <span className="sp" />
        <div className="rel wide-only">
          <button type="button" className="btn" onClick={() => setColMenu(!colMenu)} aria-expanded={colMenu}><Icon name="columns" />Columns</button>
          {colMenu && (
            <div className="menu" style={{ right: 0, top: 36 }}>
              {([['realized', 'Realized P&L'], ['held', 'Held vs 35-session time stop'], ['pending', 'Pending order']] as const).map(([id, l]) => (
                <label key={id} className="row" style={{ height: 32, padding: '0 10px', fontSize: 12.5, cursor: 'pointer' }}>
                  <input type="checkbox" className="chk" checked={table.getColumn(id)!.getIsVisible()} onChange={table.getColumn(id)!.getToggleVisibilityHandler()} />{l}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      <section className="panel">
        <div className="ph">
          <h3>{hd.title}</h3><BookTag acct={hd.tagCls === 'acct'} style={{ marginLeft: 0 }}>{hd.tag}</BookTag><span className="hint">{hd.count}</span>
          <Fresh cls={hd.frCls} l={hd.frL} />
        </div>
        {hd.errNote && <div className="pb" style={{ paddingBottom: 0 }}><Note tone="danger">{hd.errText}</Note></div>}
        {hd.noAcct && (
          <Empty title="No broker account in Ghost" actions={<button type="button" className="btn" onClick={() => setBook('model')}>Show the Model book</button>}>
            Ghost rehearses against the twin’s book; there is nothing to reconcile yet. The Alpaca paper account starts in cash on Mon 2 Nov 2026, and this view fills from Cycle B that morning.
          </Empty>
        )}
        {hd.main && (
          <>
            <div className="twrap wide-only" style={{ maxHeight: 640 }}>
              <div className="dt flush" role="table" aria-label={hd.title}>
                <div className="dt-r dt-h" role="row" style={{ gridTemplateColumns: gridCols }}>
                  {visible.map((c) => {
                    const m = c.columnDef.meta as ColMeta;
                    return <span key={c.id} role="columnheader" className={cx(m.stick && 'stick', m.cls?.includes('r') && 'r')}>{m.head}</span>;
                  })}
                </div>
                {table.getRowModel().rows.map((row) => {
                  const h = row.original;
                  const open = menu === h.s;
                  return (
                    <Fragment key={row.id}>
                      <div className={cx('dt-r', (open || drawer === h.s) && 'sel')} role="row" style={{ gridTemplateColumns: gridCols }}>
                        {row.getVisibleCells().map((cell) => {
                          const m = cell.column.columnDef.meta as ColMeta;
                          return <span key={cell.id} role="cell" className={cx(m.stick && 'stick', m.cls)}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</span>;
                        })}
                      </div>
                      {open && (
                        <div className="dt-x row wrap" style={{ gap: 8 }}>
                          <span className="xs muted">Overrides for <b className="dim">{h.s}</b> · effective tonight’s 19:15 ET submit</span>
                          <button type="button" className="btn sm" onClick={() => dispatch(control(h.locked ? 'unlock' : 'lock', h.s))}>{h.locked ? 'Unlock' : 'Lock'}</button>
                          <button type="button" className="btn sm" onClick={() => dispatch(control('trim', h.s))}>Trim…</button>
                          <button type="button" className="btn sm danger-o" onClick={() => dispatch(control('force_exit', h.s))}>Force exit…</button>
                          <button type="button" className="btn sm ghost" onClick={() => dispatch(nav('orders', { tab: 'history' }))}>View orders</button>
                        </div>
                      )}
                    </Fragment>
                  );
                })}
                <div className="dt-r dt-tot" role="row" style={{ gridTemplateColumns: gridCols }}>
                  {visible.map((c) => {
                    const m = c.columnDef.meta as ColMeta;
                    const v = totals[c.id];
                    return <span key={c.id} className={cx(m.stick && 'stick', ['val', 'unrealized', 'realized'].includes(c.id) && 'r num')}>{v}</span>;
                  })}
                </div>
              </div>
            </div>
            <div className="narrow-only">
              {hd.rows.map((h) => <HoldingCard key={h.s} h={h} onOpen={openDrawer} pending />)}
              <div className="mcard" style={{ background: 'var(--bg-2)' }}>
                <span className="row sm"><span className="b">Total {hd.tMV}</span><span className="sp" /><span className={hd.tUCls}>{hd.tU}</span></span>
                <span className="xs muted">Cash {hd.cash} · Equity {hd.eq} · weighted confidence {hd.tC}</span>
              </div>
            </div>
            {hd.none && <Empty icon={null} title="No holdings match these filters" actions={<button type="button" className="btn" onClick={() => setFl(NO_FILTERS)}>Clear filters</button>} />}
          </>
        )}
        {hd.side && <SideBySide />}
      </section>
    </div>
  );
}

const SIDE_COLS = '150px 90px 100px 90px 110px 120px 100px 90px 100px 84px minmax(240px, 1fr)';

function SideBySide() {
  const ctx = useCtx();
  const { positions, openDrawer } = useConsole();
  const sd = selectSide(ctx, positions);
  return (
    <>
      <div className="pb" style={{ paddingBottom: 0 }}><Note tone={sd.noteCls === 'warn' ? 'warn' : 'info'}>{sd.note}</Note></div>
      <div className="twrap wide-only" style={{ marginTop: 12 }}>
        <div className="dt flush">
          <div className="dt-r dt-h" style={{ gridTemplateColumns: SIDE_COLS }}>
            <span className="stick">Symbol</span><span className="r">Model sh</span><span className="r acct">Account sh</span><span className="c">Drift</span><span className="r">Model value</span><span className="r acct">Account value</span><span className="r">Δ value</span><span className="r">Model avg</span><span className="r acct">Account avg</span><span className="r">Slippage</span><span>Explanation</span>
          </div>
          {sd.rows.map((r) => (
            <div key={r.s} className="dt-r" style={{ gridTemplateColumns: SIDE_COLS }}>
              <span className="stick"><button type="button" className="linkbtn" onClick={() => openDrawer(r.s)}><span className="sym">{r.s}</span></button></span>
              <span className="r num">{r.mSh}</span><span className="r num">{r.aSh}</span>
              <span className="c"><Chip cls={r.dCls}>{r.dSh}</Chip></span>
              <span className="r num">{r.mV}</span><span className="r num">{r.aV}</span><span className={cx('r num', r.dVCls)}>{r.dV}</span>
              <span className="r num">{r.mA}</span><span className="r num">{r.aA}</span><span className={cx('r num', r.slipCls)}>{r.slip}</span>
              <span className="wc dim">{r.ex}</span>
            </div>
          ))}
          <div className="dt-r dt-tot" style={{ gridTemplateColumns: SIDE_COLS }}>
            <span className="stick">Equity</span><span /><span /><span className="c">{sd.drift}</span><span className="r num">{sd.mEq}</span><span className="r num">{sd.aEq}</span><span className={cx('r num', sd.dEqCls)}>{sd.dEq}</span><span /><span /><span />
            <span className="dim" style={{ fontWeight: 500 }}>cash: Model {sd.mCash} · Account {sd.aCash}</span>
          </div>
        </div>
      </div>
      <div className="narrow-only" style={{ marginTop: 12 }}>
        {sd.rows.map((r) => (
          <div key={r.s} className="mcard">
            <span className="mcard-h"><span className="sym">{r.s}</span><span className="sp" /><Chip cls={r.dCls}>{r.dSh}</Chip></span>
            <span className="mcard-g">
              <span><span className="l">Model</span><span className="v">{r.mSh} sh</span></span>
              <span><span className="l">Account</span><span className="v acct">{r.aSh} sh</span></span>
              <span><span className="l">Δ value</span><span className={cx('v', r.dVCls)}>{r.dV}</span></span>
            </span>
            <span className="xs muted">{r.ex}</span>
          </div>
        ))}
      </div>
    </>
  );
}
