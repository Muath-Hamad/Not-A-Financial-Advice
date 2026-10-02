// Hover (or focus, or tap) a dotted-underlined term to see a plain-English
// explanation card. <T k="atr">ATR</T> marks one term; <Gloss text="…" />
// finds known terms inside free text such as order reasons.

import { Fragment, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cx } from '@/lib/format';
import { ALIASES, TERMS, type Entry, type TermKey } from './terms';

const OPEN_MS = 140;
const CLOSE_MS = 120;

export function T({ k, children, className }: { k: TermKey; children?: ReactNode; className?: string }) {
  const entry: Entry = TERMS[k];
  const ref = useRef<HTMLSpanElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const id = useId();
  const later = (v: boolean, ms: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(v), ms);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <>
      <span
        ref={ref}
        className={cx('term', className)}
        tabIndex={0}
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => later(true, OPEN_MS)}
        onMouseLeave={() => later(false, CLOSE_MS)}
        onFocus={() => later(true, 0)}
        onBlur={() => later(false, CLOSE_MS)}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false); }}
      >
        {children ?? entry.title}
      </span>
      {open && ref.current && (
        <Card id={id} entry={entry} anchor={ref.current} keep={() => window.clearTimeout(timer.current)} leave={() => later(false, CLOSE_MS)} />
      )}
    </>
  );
}

function Card({ id, entry, anchor, keep, leave }: { id: string; entry: Entry; anchor: HTMLElement; keep: () => void; leave: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  useLayoutEffect(() => {
    const r = anchor.getBoundingClientRect();
    const el = ref.current;
    const w = el?.offsetWidth ?? 300;
    const h = el?.offsetHeight ?? 120;
    const left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 8));
    const below = r.bottom + 8;
    const top = below + h > window.innerHeight - 8 ? Math.max(8, r.top - h - 8) : below;
    setPos({ left, top });
  }, [anchor]);
  const host = (anchor.closest('.nafa') as HTMLElement | null) ?? document.body;
  return createPortal(
    <div
      ref={ref}
      id={id}
      role="tooltip"
      className="gloss-pop"
      style={{ left: pos?.left ?? -9999, top: pos?.top ?? -9999 }}
      onMouseEnter={keep}
      onMouseLeave={leave}
    >
      <b className="gt">{entry.title}</b>
      <span>{entry.plain}</span>
      {entry.here && <span className="gh">{entry.here}</span>}
    </div>,
    host,
  );
}

/** Mark every known term (first occurrence of each) inside a piece of text. */
export function Gloss({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  const hits: { i: number; j: number; k: TermKey }[] = [];
  const seen = new Set<TermKey>();
  for (const [re, k] of ALIASES) {
    if (seen.has(k)) continue;
    const m = re.exec(text);
    if (!m) continue;
    const i = m.index;
    const j = i + m[0].length;
    if (hits.some((h) => i < h.j && j > h.i)) continue;
    hits.push({ i, j, k });
    seen.add(k);
  }
  if (!hits.length) return <>{text}</>;
  hits.sort((a, b) => a.i - b.i);
  const out: ReactNode[] = [];
  let at = 0;
  hits.forEach((h, n) => {
    if (h.i > at) out.push(<Fragment key={'t' + n}>{text.slice(at, h.i)}</Fragment>);
    out.push(<T key={'g' + n} k={h.k}>{text.slice(h.i, h.j)}</T>);
    at = h.j;
  });
  if (at < text.length) out.push(<Fragment key="end">{text.slice(at)}</Fragment>);
  return <>{out}</>;
}
