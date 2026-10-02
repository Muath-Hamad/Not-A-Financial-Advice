// Thin ECharts host: one instance per element, resized with its container,
// re-themed when the app theme changes.

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { echarts, readTokens, type ChartTokens } from './echarts';
import { useConsole } from '@/app/console';

export function useChartTokens(): [React.RefObject<HTMLDivElement>, ChartTokens | null] {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useConsole();
  const [tokens, setTokens] = useState<ChartTokens | null>(null);
  useLayoutEffect(() => {
    setTokens(readTokens(ref.current));
  }, [theme]);
  return [ref, tokens];
}

export function Chart({ option, style, ariaLabel, group }: { option: EChartsCoreOption | null; style?: CSSProperties; ariaLabel: string; group?: string }) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<ReturnType<typeof echarts.init> | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const chart = echarts.init(el.current, undefined, { renderer: 'canvas' });
    if (group) chart.group = group;
    inst.current = chart;
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => chart.resize()) : null;
    ro?.observe(el.current);
    return () => {
      ro?.disconnect();
      chart.dispose();
      inst.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (inst.current && option) inst.current.setOption(option, { notMerge: true });
  }, [option]);

  return <div ref={el} role="img" aria-label={ariaLabel} style={{ width: '100%', ...style }} />;
}
