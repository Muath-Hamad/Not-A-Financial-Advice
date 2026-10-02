// Client-side CSV export of what the table shows (docs/08 §8 exports).

function cell(v: string): string {
  return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
}

export function toCsv(head: string[], rows: string[][]): string {
  return [head, ...rows].map((r) => r.map(cell).join(',')).join('\n') + '\n';
}

export function exportCsv(name: string, head: string[], rows: string[][]): void {
  const blob = new Blob([toCsv(head, rows)], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
