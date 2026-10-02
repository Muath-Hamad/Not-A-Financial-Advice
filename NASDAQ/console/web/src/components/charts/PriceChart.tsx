// Holding price pane: 70 sessions of closes with SMA50/SMA200, the average
// cost, the initial and trailing stops, and the entry fill.

import { useMemo } from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { spct, usd } from '@/lib/format';
import type { PriceView } from '@/domain/holdings';
import { Chart, useChartTokens } from './Chart';
import { FONT, type ChartTokens } from './echarts';

function level(y: number, text: string, color: string, border: string, t: ChartTokens, type: 'dashed' | 'dotted' = 'dashed') {
  return {
    yAxis: y,
    lineStyle: { type, color, width: 1 },
    label: { formatter: text, position: 'insideEndTop', distance: [0, -8], color, fontSize: 10, backgroundColor: t.bg1, borderColor: border, borderWidth: 1, borderRadius: 3, padding: [1, 5] },
  };
}

export function PriceChart({ v }: { v: PriceView }) {
  const [ref, t] = useChartTokens();
  const option = useMemo<EChartsCoreOption | null>(() => {
    if (!t) return null;
    const n = v.close.length;
    const keep = new Set([0, 23, 46, n - 1]);
    const lines = [level(v.avg, 'Avg ' + usd(v.avg), t.fg2, t.line2, t)];
    if (v.initialStop != null) lines.push(level(v.initialStop, 'Initial stop ' + usd(v.initialStop), t.danger, t.dangerLine, t));
    if (v.trailingStop != null) lines.push(level(v.trailingStop, 'Trailing ' + usd(v.trailingStop), t.warn, t.warnLine, t));
    const thin = (name: string, data: (number | null)[], color: string) => ({ name, type: 'line', data, showSymbol: false, connectNulls: false, lineStyle: { color, width: 1.1, opacity: 0.85 }, itemStyle: { color } });
    return {
      animation: false,
      textStyle: { fontFamily: FONT },
      grid: { left: 0, right: 0, top: 8, bottom: 20 },
      xAxis: {
        type: 'category', data: v.labels, boundaryGap: false,
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
        axisLabel: { color: t.fg3, fontSize: 10.5, interval: (i: number) => keep.has(i), alignMinLabel: 'left', alignMaxLabel: 'right', margin: 5 },
        axisPointer: { show: true, type: 'line', lineStyle: { color: t.fg3, opacity: 0.8 }, label: { show: false } },
      },
      yAxis: { type: 'value', min: v.lo, max: v.hi, show: false },
      tooltip: {
        trigger: 'axis', backgroundColor: 'transparent', borderWidth: 0, padding: 0, extraCssText: 'box-shadow:none;',
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0]?.dataIndex ?? 0;
          const after = i >= v.entryIndex;
          const vs = after ? spct((v.close[i] / v.avg - 1) * 100) : 'before entry';
          const cls = after ? (v.close[i] >= v.avg ? 'pos' : 'neg') : 'muted';
          return '<div class="tip" style="position:static;min-width:160px"><div class="b">' + v.wlabels[i] + '</div>'
            + '<div class="tr"><span>Close</span><span class="num">' + usd(v.close[i]) + '</span></div>'
            + '<div class="tr"><span>SMA50</span><span class="num">' + (v.sma50[i] == null ? '—' : usd(v.sma50[i] as number)) + '</span></div>'
            + '<div class="tr"><span>vs avg cost</span><span class="num ' + cls + '">' + vs + '</span></div></div>';
        },
      },
      series: [
        thin('SMA200', v.sma200, t.acct),
        thin('SMA50', v.sma50, t.info),
        {
          name: 'Close', type: 'line', data: v.close, showSymbol: false, lineStyle: { color: t.fg1, width: 1.6 }, itemStyle: { color: t.fg1 },
          markLine: { symbol: 'none', silent: true, data: lines },
          markPoint: v.entryIndex >= 0 && v.entryIndex < n
            ? { symbol: 'circle', symbolSize: 16, itemStyle: { color: t.fg1 }, label: { show: true, formatter: 'B', color: t.bg1, fontSize: 9, fontWeight: 700 }, data: [{ coord: [v.entryIndex, v.avg], name: v.entryText }], tooltip: { formatter: () => '<div class="tip" style="position:static;min-width:0">' + v.entryText + '</div>' } }
            : undefined,
        },
      ],
    };
  }, [v, t]);
  return (
    <div ref={ref}>
      <Chart option={option} style={{ height: 210 }} ariaLabel={'Price over ' + v.close.length + ' sessions with SMA50, SMA200, average cost and stops'} />
    </div>
  );
}
