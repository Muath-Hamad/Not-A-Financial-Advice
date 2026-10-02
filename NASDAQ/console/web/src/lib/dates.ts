// Session dates arrive as ISO `YYYY-MM-DD` (market dates, no time zone).
// Labels follow the prototype: "25 Sep" on axes, "Fri 25 Sep" in tables.

const MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function parts(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

/** "25 Sep" */
export function dayLabel(iso: string): string {
  const dt = parts(iso);
  return dt.getUTCDate() + ' ' + MO[dt.getUTCMonth()];
}

/** "Fri 25 Sep" */
export function wdLabel(iso: string): string {
  const dt = parts(iso);
  return WD[dt.getUTCDay()] + ' ' + dt.getUTCDate() + ' ' + MO[dt.getUTCMonth()];
}

/** "20260925" */
export function compact(iso: string): string {
  return iso.replace(/-/g, '');
}

/** Weekdays (minus the given holidays) ending at `end`, oldest first. */
export function sessionsEndingAt(end: string, n: number, holidays: Set<string> = new Set()): string[] {
  const out: string[] = [];
  const dt = parts(end);
  while (out.length < n) {
    const wd = dt.getUTCDay();
    const k = dt.toISOString().slice(0, 10);
    if (wd !== 0 && wd !== 6 && !holidays.has(k)) out.unshift(k);
    dt.setUTCDate(dt.getUTCDate() - 1);
  }
  return out;
}

/** "Mon" */
export function dow(iso: string): string {
  return WD[parts(iso).getUTCDay()];
}

/** Whole calendar days from a to b (b − a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((parts(b).getTime() - parts(a).getTime()) / 86_400_000);
}

/** Age in plain words: "2 min", "5 h", "6 d". */
export function ago(min: number | null | undefined): string {
  if (min == null) return '—';
  if (min < 60) return Math.max(0, Math.round(min)) + ' min';
  if (min < 1440) return Math.round(min / 60) + ' h';
  return Math.round(min / 1440) + ' d';
}

/** Countdown: "1h12m", "45m". */
export function hm(min: number | null | undefined): string {
  if (min == null) return '';
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h ? h + 'h' + String(m).padStart(2, '0') + 'm' : m + 'm';
}
