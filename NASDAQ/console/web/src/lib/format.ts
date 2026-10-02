// Number and text formatting shared by every selector. Ported from the
// prototype's Component helpers (f, usd, susd, spct, tn, band, …) so the copy
// matches it character for character: a true minus sign (−), and a + on every
// signed money or percentage value.

export type Tone = 'pos' | 'neg' | 'dim';
export type Band = 'high' | 'med' | 'low';

/** Absolute value with fixed decimals and thousands separators. */
export function f(v: number, d = 2): string {
  return Math.abs(+v || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** $1,234.56 or −$1,234.56 */
export function usd(v: number, d?: number): string {
  return (v < 0 ? '−$' : '$') + f(v, d);
}

/** Signed money: +$1.00, −$1.00, $0.00 */
export function susd(v: number, d?: number): string {
  if (Math.abs(v) < 0.005) return '$0.00';
  return (v > 0 ? '+$' : '−$') + f(v, d);
}

/** Signed percent: +1.2%, −1.2%, 0.0% */
export function spct(v: number, d = 1): string {
  const r = +(+v).toFixed(d);
  if (r === 0) return f(0, d) + '%';
  return (r > 0 ? '+' : '−') + f(r, d) + '%';
}

/** Tone class for a P&L number. */
export function tn(v: number): Tone {
  return v > 0.004 ? 'pos' : v < -0.004 ? 'neg' : 'dim';
}

/** Confidence band (docs/08 §6): High ≥ 70 · Medium 40–69 · Low < 40. */
export function band(c: number): Band {
  return c >= 70 ? 'high' : c >= 40 ? 'med' : 'low';
}

export function bandL(c: number): 'High' | 'Medium' | 'Low' {
  return c >= 70 ? 'High' : c >= 40 ? 'Medium' : 'Low';
}

/** Deterministic PRNG (Park–Miller), for illustrative series only. */
export function rng(seedValue: number): () => number {
  let x = (Math.abs(seedValue) % 2147483646) + 1;
  return () => {
    x = (x * 16807) % 2147483647;
    return (x - 1) / 2147483646;
  };
}

export function seed(s: string): number {
  let h = 7;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 2147483647;
  return h;
}

/** SVG path for a series in a W×H box; nulls break the line. */
export function path(vals: (number | null)[], lo: number, hi: number, W: number, H: number): string {
  const n = vals.length;
  let out = '';
  let pen = false;
  for (let i = 0; i < n; i++) {
    const v = vals[i];
    if (v == null) {
      pen = false;
      continue;
    }
    const x = n === 1 ? 0 : (i / (n - 1)) * W;
    const y = H - ((v - lo) / (hi - lo || 1)) * H;
    out += (pen ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1) + ' ';
    pen = true;
  }
  return out.trim();
}

/** Sparkline path with 10% vertical padding, in a 100×26 box. */
export function spark(arr: number[]): string {
  const lo = Math.min(...arr);
  const hi = Math.max(...arr);
  return path(arr, lo - (hi - lo) * 0.1, hi + (hi - lo) * 0.1, 100, 26);
}

/** Round axis ticks between lo and hi, about n of them. */
export function ticks(lo: number, hi: number, n: number): number[] {
  const span = hi - lo;
  const raw = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((k) => span / k <= n) || mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

export interface HBar {
  l: string;
  n: string;
  v: string;
  tCls: Tone;
  z: string;
  x: string;
  w: string;
  cls: 'pos' | 'neg';
}

/** Diverging horizontal bars around a zero line, widths in % of the track. */
export function hbars(items: { l: string; n?: string; v: number }[]): HBar[] {
  const vs = items.map((i) => i.v);
  const lo = Math.min(0, ...vs);
  const hi = Math.max(0, ...vs);
  const span = hi - lo || 1;
  const z = (-lo / span) * 100;
  return items.map((i) => {
    const w = (Math.abs(i.v) / span) * 100;
    return {
      l: i.l,
      n: i.n || '',
      v: susd(i.v),
      tCls: tn(i.v),
      z: z.toFixed(2),
      x: (i.v >= 0 ? z : z - w).toFixed(2),
      w: (i.v === 0 ? 0 : Math.max(w, 0.6)).toFixed(2),
      cls: i.v >= 0 ? 'pos' : 'neg',
    };
  });
}

/** Join class names, dropping falsy parts. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}
