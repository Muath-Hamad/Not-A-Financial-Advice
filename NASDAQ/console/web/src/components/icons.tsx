// Stroke icons from the prototype (24×24, currentColor, class "ic").

import type { ReactNode } from 'react';

const P: Record<string, ReactNode> = {
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  bell: <><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5Z" />,
  octagon: <><path d="M8 3h8l5 5v8l-5 5H8l-5-5V8l5-5Z" /><path d="M12 8v5M12 16h.01" /></>,
  triangle: <><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17h.01" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  overview: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  holdings: <><path d="M12 3 3 8l9 5 9-5-9-5Z" /><path d="m3 13 9 5 9-5" /></>,
  orders: <><path d="M9 6h12M9 12h12M9 18h12" /><path d="M4 6h.01M4 12h.01M4 18h.01" /></>,
  performance: <><path d="M3 17l6-6 4 4 8-8" /><path d="M14 7h7v7" /></>,
  compliance: <><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6l8-3Z" /><path d="m9 12 2 2 4-4" /></>,
  controls: <><path d="M12 3v9" /><path d="M18.4 6.6a9 9 0 1 1-12.8 0" /></>,
  agent: <><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></>,
  health: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  audit: <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>,
  roadmap: <><path d="M4 21V4" /><path d="M4 4h12l-2 4 2 4H4" /></>,
  book: <><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5Z" /><path d="M4 19a2 2 0 0 1 2-2h13" /><path d="M9 7h6" /></>,
  settings: <><path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1" /><circle cx="15" cy="6" r="2" /><circle cx="9" cy="12" r="2" /><circle cx="17" cy="18" r="2" /></>,
  proto: <><rect x="3" y="3" width="18" height="18" rx="3" style={{ strokeDasharray: '3 3' }} /><path d="M9 9h6v6H9z" /></>,
  more: <><circle cx="5" cy="12" r="1.3" /><circle cx="12" cy="12" r="1.3" /><circle cx="19" cy="12" r="1.3" /></>,
  lock: <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  download: <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />,
  columns: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M15 4v16" /></>,
  copy: <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  back: <path d="m15 18-6-6 6-6" />,
  chevron: <path d="m9 18 6-6-6-6" />,
  check: <path d="m5 12 5 5 9-10" />,
  refresh: <path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4" />,
};

export type IconName = keyof typeof P;

export function Icon({ name, className = '', style }: { name: IconName; className?: string; style?: React.CSSProperties }) {
  return (
    <svg className={'ic ' + className} viewBox="0 0 24 24" aria-hidden="true" style={style}>
      {P[name]}
    </svg>
  );
}

/** Severity glyph used by banners, attention items and notes. */
export function ToneIcon({ tone, className = '' }: { tone: 'red' | 'amber' | 'blue' | 'danger' | 'warn' | 'info' | 'ok' | string; className?: string }) {
  const name: IconName = tone === 'red' || tone === 'danger' ? 'octagon' : tone === 'amber' || tone === 'warn' ? 'triangle' : 'info';
  return <Icon name={name} className={className} />;
}
