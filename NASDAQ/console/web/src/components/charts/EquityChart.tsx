// Equity (Model, Account, NASDAQ Composite) over drawdown, two ECharts
// instances connected so they share one x-axis crosshair (HANDOFF §4.11).
// Markers: ◆ adaptation, ⚑ override, ■ halt.

import { useEffect, useMemo, useState } from 'react';
import type { EChartsCoreOption } from 'echarts/core';
import { spct, usd } from '@/lib/format';
import type { EquityView } from '@/domain/overview';
import { Chart, useChartTokens } from './Chart';
import { echarts, FONT, type ChartTokens } from './echarts';

let groupSeq = 0;

function tickIdx(n: number): Set<number> {
  if (n <= 8) return new Set(Array.from({ length: n }, (_, i) => i));
  return new Set([0, Math.round((n - 1) * 0.25), Math.round((n - 1) * 0.5), Math.round((n - 1) * 0.75), n - 1]);
}

function xAxis(v: EquityView, t: ChartTokens, labels: boolean) {
  const keep = tickIdx(v.labels.length);
  return {
    type: 'category', data: v.labels, boundaryGap: false,
    axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false },
    axisLabel: labels
      ? { show: true, color: t.fg3, fontSize: 10.5, fontFamily: FONT, interval: (i: number) => keep.has(i), alignMinLabel: 'left', alignMaxLabel: 'right', margin: 6 }
      : { show: false },
    axisPointer: { show: true, type: 'line', lineStyle: { color: t.fg3, width: 1, opacity: 0.8 }, label: { show: false } },
  };
}

const MARK_COLOR = (t: ChartTokens, cls: string) => (cls === 'halt' ? t.danger : cls === 'ovr' ? t.warn : t.info);

export function EquityChart({ v, mainH, ddH, ddLabel }: { v: EquityView; mainH: number; ddH: number; ddLabel?: React.ReactNode }) {
  const [ref, t] = useChartTokens();
  const [group] = useState(() => 'eq' + ++groupSeq);
  useEffect(() => {
    const id = window.setTimeout(() => echarts.connect(group), 0);
    return () => { window.clearTimeout(id); echarts.disconnect(group); };
  }, [group]);

  const main = useMemo<EChartsCoreOption | null>(() => {
    if (!t) return null;
    const all = [...v.model, ...v.bench, ...((v.account ?? []).filter((x) => x != null) as number[])];
    let lo = Math.min(...all);
    let hi = Math.max(...all);
    const pad = (hi - lo) * 0.1;
    lo -= pad;
    hi += pad;
    const series: object[] = [
      { name: 'NASDAQ', type: 'line', data: v.bench, showSymbol: false, lineStyle: { color: t.bench, width: 1.75, type: [4, 3] }, itemStyle: { color: t.bench }, z: 1 },
    ];
    if (v.account) series.push({ name: 'Account', type: 'line', data: v.account, showSymbol: false, connectNulls: false, lineStyle: { color: t.acct, width: 1.75 }, itemStyle: { color: t.acct }, z: 2 });
    series.push({
      name: 'Model', type: 'line', data: v.model, showSymbol: false, lineStyle: { color: t.model, width: 2 }, itemStyle: { color: t.model }, z: 3,
      markPoint: {
        symbol: 'circle', symbolSize: 1, silent: false,
        data: v.marks.map((m) => ({ coord: [m.i, v.model[m.i]], value: m.g, name: m.t, label: { show: true, formatter: m.g, position: 'top', distance: 8, color: MARK_COLOR(t, m.cls), fontSize: 12, textBorderColor: t.bg1, textBorderWidth: 3 }, itemStyle: { color: 'transparent' } })),
        tooltip: { show: true, formatter: (p: { name: string }) => '<div class="tip" style="position:static;min-width:0">' + p.name + '</div>' },
      },
    });
    return {
      animation: false,
      textStyle: { fontFamily: FONT },
      grid: { left: 0, right: 58, top: 6, bottom: 22 },
      xAxis: xAxis(v, t, true),
      yAxis: {
        type: 'value', position: 'right', min: lo, max: hi, splitNumber: 4,
        axisLabel: { color: t.fg3, fontSize: 10.5, formatter: (x: number) => '$' + (x / 1000).toFixed(x % 1000 ? 1 : 0) + 'k', margin: 8 },
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: t.line1 } },
      },
      tooltip: {
        trigger: 'axis', backgroundColor: 'transparent', borderWidth: 0, padding: 0, extraCssText: 'box-shadow:none;',
        formatter: (ps: { dataIndex: number }[]) => {
          const i = ps[0]?.dataIndex ?? 0;
          const mk = v.marks.find((m) => m.i === i);
          const row = (sw: string, l: string, val: string, cls = '') => '<div class="tr"><span class="row gap4"><i class="sw ' + sw + '"></i>' + l + '</span><span class="num ' + cls + '">' + val + '</span></div>';
          return '<div class="tip" style="position:static">'
            + '<div class="b">' + v.wlabels[i] + ' ' + v.dates[i].slice(0, 4) + '</div>'
            + row('model', 'Model', usd(v.model[i]))
            + row('acct', 'Account', v.account && v.account[i] != null ? usd(v.account[i] as number) : '—')
            + row('bench', 'NASDAQ', usd(v.bench[i]))
            + row('dd', 'Drawdown', spct(v.dd[i]), 'neg')
            + (mk ? '<div class="xs warn" style="margin-top:3px;white-space:normal">' + mk.g + ' ' + mk.t + '</div>' : '')
            + '</div>';
        },
      },
      series,
    };
  }, [v, t]);

  const dd = useMemo<EChartsCoreOption | null>(() => {
    if (!t) return null;
    const min = Math.min(-26, Math.min(...v.dd) * 1.05);
    return {
      animation: false,
      grid: { left: 0, right: 58, top: 2, bottom: 4 },
      xAxis: xAxis(v, t, false),
      yAxis: { type: 'value', min, max: 0, show: true, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
      tooltip: { trigger: 'axis', showContent: false },
      series: [{
        name: 'Drawdown', type: 'line', data: v.dd, showSymbol: false,
        lineStyle: { color: t.neg, width: 1.25 }, areaStyle: { color: t.negBg, origin: 'auto' }, itemStyle: { color: t.neg },
        markLine: {
          symbol: 'none', silent: true,
          data: [
            { yAxis: v.refDD, lineStyle: { type: 'dotted', color: t.fg3, width: 1 }, label: { formatter: '−16.2%' + (ddLabel ? '' : ' ref'), position: 'end', color: t.fg3, fontSize: 10.5 } },
            { yAxis: v.killDD, lineStyle: { type: 'dashed', color: t.danger, width: 1 }, label: { formatter: '−25% kill', position: 'end', color: t.danger, fontSize: 10.5 } },
          ],
        },
      }],
    };
  }, [v, t, ddLabel]);

  return (
    <div ref={ref}>
      <Chart option={main} style={{ height: mainH, marginTop: 10 }} ariaLabel="Equity: Model, Account and NASDAQ Composite, rebased to $100k" group={group} />
      {ddLabel}
      <Chart option={dd} style={{ height: ddH, marginTop: ddLabel ? 6 : 14 }} ariaLabel="Drawdown from peak against the −16.2% reference and −25% kill line" group={group} />
    </div>
  );
}
