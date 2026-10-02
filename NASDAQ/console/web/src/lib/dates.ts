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
