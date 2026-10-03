// Shared presentational components from the component sheet
// (docs/09c prototype/Components.dc.html). Class names are nafa.css's.

import type { CSSProperties, ReactNode } from 'react';
import { cx } from '@/lib/format';
import type { LcStep } from '@/domain/core';
import { Icon, ToneIcon } from './icons';
import { Gloss, T } from '@/glossary/Term';

export function Panel({ title, hint, extra, fresh, className, style, children, footer }: {
  title?: ReactNode;
  hint?: ReactNode;
  extra?: ReactNode;
  fresh?: { cls?: string; l: string } | null;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <section className={cx('panel', className)} style={style}>
      {(title || hint || extra || fresh) && (
        <div className="ph">
          {title && <h3>{title}</h3>}
          {hint && <span className="hint">{hint}</span>}
          {extra}
          {fresh && <Fresh {...fresh} />}
        </div>
      )}
      {children}
      {footer && <div className="pf">{footer}</div>}
    </section>
  );
}

export function Fresh({ cls, l, style }: { cls?: string; l: string; style?: CSSProperties }) {
  return <span className={cx('fresh', cls)} style={style}>{l}</span>;
}

export function PageHeader({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-h">
      <div className="col gap4"><h1>{title}</h1>{sub && <span className="sub">{sub}</span>}</div>
      {children}
    </div>
  );
}

export function Seg<T extends string>({ items, value, onChange, label, className }: {
  items: { k: T; l: ReactNode }[];
  value: T;
  onChange: (k: T) => void;
  label: string;
  className?: string;
}) {
  return (
    <div className={cx('seg', className)} role="group" aria-label={label}>
      {items.map((it, i) => (
        <button key={it.k + i} type="button" className={value === it.k ? 'on' : ''} aria-pressed={value === it.k} onClick={() => onChange(it.k)}>{it.l}</button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ items, value, onChange }: { items: { k: T; l: ReactNode; n?: string }[]; value: T; onChange: (k: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((it) => (
        <button key={it.k} type="button" role="tab" aria-selected={value === it.k} className={cx('tab', value === it.k && 'on')} onClick={() => onChange(it.k)}>
          {it.l}{it.n != null && <span className="n">{it.n}</span>}
        </button>
      ))}
    </div>
  );
}

export function Chip({ cls, children, title, style }: { cls?: string; children: ReactNode; title?: string; style?: CSSProperties }) {
  return <span className={cx('chip', cls)} title={title} style={style}>{children}</span>;
}

export function Grade({ g, gCls, xl, style, title }: { g: string; gCls?: string; xl?: boolean; style?: CSSProperties; title?: string }) {
  return <span className={cx('grade', xl && 'xl', gCls ?? 'g' + g)} style={style} title={title ?? 'Sharia grade ' + g}>{g}</span>;
}

export function Shar({ g, gCls, stat }: { g: string; gCls: string; stat: string }) {
  return <span className="shar"><Grade g={g} gCls={gCls} />{stat}</span>;
}

/** Confidence: number, four-segment micro-bar, band label. */
export function Conf({ c, band, bandL, segs, title, bar = true, label = true }: {
  c: string;
  band: string;
  bandL?: string;
  segs?: { w: number; f: number }[];
  title?: string;
  bar?: boolean;
  label?: boolean;
}) {
  if (band === 'none') {
    return (
      <span className="conf" title={title ?? 'Pending — confidence comes from the insights step, which runs in Cycle A'}>
        <span className="conf-n muted">—</span>
        {label && <span className="conf-b muted">Pending</span>}
      </span>
    );
  }
  return (
    <span className={cx('conf', band)} title={title}>
      <span className="conf-n">{c}</span>
      {bar && segs && <MicroBar segs={segs} />}
      {label && bandL && <span className="conf-b">{bandL}</span>}
    </span>
  );
}

export function MicroBar({ segs, className }: { segs: { w: number; f: number }[]; className?: string }) {
  return (
    <span className={cx('mb', className)}>
      {segs.map((g, i) => (
        <span key={i} className="mb-s" style={{ flex: g.w }}><i className="mb-f" style={{ width: g.f + '%' }} /></span>
      ))}
    </span>
  );
}

export function BookTag({ acct, children, style }: { acct?: boolean; children: ReactNode; style?: CSSProperties }) {
  const k = children === 'ACCOUNT' ? 'account' : children === 'BOTH' ? 'drift' : 'model';
  return <span className={cx('booktag', acct && 'acct')} style={style}><T k={k}>{children}</T></span>;
}

export function SideTag({ side, label }: { side: 'buy' | 'sell' | string; label: ReactNode }) {
  return <span className={cx('side', side)}>{label}</span>;
}

export function Note({ tone, children, className }: { tone?: string; children: ReactNode; className?: string }) {
  return (
    <div className={cx('note', tone, className)}>
      <ToneIcon tone={tone === 'danger' ? 'danger' : tone === 'warn' ? 'warn' : 'info'} />
      <span>{children}</span>
    </div>
  );
}

export function Empty({ icon = 'clock', title, children, actions, style }: { icon?: Parameters<typeof Icon>[0]['name'] | null; title: ReactNode; children?: ReactNode; actions?: ReactNode; style?: CSSProperties }) {
  return (
    <div className="empty" style={style}>
      {icon && <span className="ei"><Icon name={icon} className="s22" /></span>}
      <h4>{title}</h4>
      {children && <p>{children}</p>}
      {actions && <div className="row wrap" style={{ justifyContent: 'center' }}>{actions}</div>}
    </div>
  );
}

export function Sk({ w, h, style }: { w?: number | string; h: number | string; style?: CSSProperties }) {
  return <span className="sk" style={{ display: 'block', width: w, height: h, ...style }} />;
}

/** Full lifecycle stepper (Intent → … → Reconciled). */
export function Lifecycle({ steps, minWidth, style }: { steps: LcStep[]; minWidth?: number; style?: CSSProperties }) {
  return (
    <div className="lcy" style={style}>
      {steps.map((x, i) => (
        <div key={i} className={cx('lcy-i', x.c)} style={minWidth ? { minWidth } : undefined}>
          <span className="lcy-dot">{x.g}</span><span className="lcy-l">{x.l}</span><span className="lcy-t">{x.t}</span>
        </div>
      ))}
    </div>
  );
}

/** Mini lifecycle dots plus the state label. */
export function MiniLifecycle({ steps, state, sc, small }: { steps: LcStep[]; state: string; sc: string; small?: boolean }) {
  return (
    <span className="lc">
      <span className="mini">{steps.map((x, i) => <span key={i} className={x.m} />)}</span>
      <span className={cx(small && 'xs', sc)}>{state}</span>
    </span>
  );
}

export function Guardrail({ ok, rule, note, small }: { ok: boolean; rule: string; note?: string; small?: boolean }) {
  if (ok) return <span className={cx('gr ok', small && 'xs')}>✓ {small ? <T k="guardrails">guardrails</T> : 'passed'}</span>;
  return (
    <>
      <span className={cx('gr blk', small && 'xs')}>⊘ {small ? null : 'blocked '}<span className="rule"><Gloss text={rule} /></span></span>
      {note && !small && <span className="xs muted" style={{ display: 'block' }}>{note}</span>}
    </>
  );
}

/** Debt or cash vs market cap, with the 30% threshold at 75% of the track (0–40%). */
export function RatioGauge({ label, r }: { label: string; r: { v: string; w: string; head: string; hCls: string; cls: string } }) {
  const k = label.startsWith('Debt') ? 'debtMcap' : 'cashMcap';
  return (
    <div className="gauge">
      <div className="gauge-lbl"><span><T k={k}>{label}</T></span><span className="num"><b className="dim">{r.v}</b> · <span className={r.hCls}>{r.head.endsWith('headroom') ? <>{r.head.replace(' headroom', ' ')}<T k="headroom">headroom</T></> : r.head}</span></span></div>
      <div className="gauge-t"><i className={cx('gauge-f', r.cls)} style={{ width: r.w + '%' }} /><i className="gauge-th" style={{ left: '75%' }} title="30% threshold" /></div>
    </div>
  );
}

export function Kv({ rows, left, style }: { rows: [ReactNode, ReactNode, string?][]; left?: boolean; style?: CSSProperties }) {
  return (
    <dl className={cx('kv', left && 'left')} style={{ margin: 0, ...style }}>
      {rows.map(([k, v, cls], i) => (
        <FragmentPair key={i} k={k} v={v} cls={cls} />
      ))}
    </dl>
  );
}

function FragmentPair({ k, v, cls }: { k: ReactNode; v: ReactNode; cls?: string }) {
  return <><dt>{k}</dt><dd className={cls}>{v}</dd></>;
}

export function Stat({ l, v, s, vCls, vStyle }: { l: ReactNode; v: ReactNode; s?: ReactNode; vCls?: string; vStyle?: CSSProperties }) {
  return (
    <div className="statbox">
      <span className="l">{l}</span>
      <span className={cx('v', vCls)} style={vStyle}>{v}</span>
      {s && <span className="xs muted">{s}</span>}
    </div>
  );
}

export function Spark({ d, className, box = '0 0 100 26', style }: { d: string; className?: string; box?: string; style?: CSSProperties }) {
  return (
    <svg viewBox={box} preserveAspectRatio="none" style={style}>
      <path className={cx('spark', className)} d={d} />
    </svg>
  );
}

export function StackBar({ segs, style }: { segs: { w: string; c: string; t: string }[]; style?: CSSProperties }) {
  return <div className="stack" style={style}>{segs.map((g, i) => <span key={i} style={{ width: g.w + '%', background: g.c }} title={g.t} />)}</div>;
}

export function HBars({ items, wrapLabel }: { items: { l: string; n: string; v: string; tCls: string; z: string; x: string; w: string; cls: string }[]; wrapLabel?: boolean }) {
  return (
    <div className="pb hbars">
      {items.map((b) => (
        <div key={b.l} className="hbar">
          <span className="dim" style={wrapLabel ? undefined : { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{b.l}{b.n && <span className="muted xs"> · {b.n}</span>}</span>
          <span className="hbar-t"><span className="z" style={{ left: b.z + '%' }} /><i className={b.cls} style={{ left: b.x + '%', width: b.w + '%' }} /></span>
          <span className={cx('r num', b.tCls)}>{b.v}</span>
        </div>
      ))}
    </div>
  );
}

export function ExportButton({ onClick, label = 'Export CSV', wideOnly }: { onClick: () => void; label?: string; wideOnly?: boolean }) {
  return (
    <button type="button" className="btn" onClick={onClick}>
      <Icon name="download" />{wideOnly ? <span className="wide-only">{label}</span> : label}
    </button>
  );
}
