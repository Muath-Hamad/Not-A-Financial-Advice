// Tree-shaken ECharts build: line series, two-grid layouts, a shared
// axisPointer crosshair, markLine/markPoint for stops, markers and limits.

import * as echarts from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { AxisPointerComponent, GridComponent, MarkLineComponent, MarkPointComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([LineChart, GridComponent, TooltipComponent, AxisPointerComponent, MarkLineComponent, MarkPointComponent, CanvasRenderer]);

export { echarts };

/** Canvas can't read CSS variables, so resolve the tokens once per theme. */
export interface ChartTokens {
  fg1: string;
  fg2: string;
  fg3: string;
  line1: string;
  line2: string;
  line3: string;
  bg1: string;
  bg3: string;
  model: string;
  acct: string;
  bench: string;
  neg: string;
  negBg: string;
  pos: string;
  warn: string;
  danger: string;
  info: string;
  dangerLine: string;
  warnLine: string;
}

const VARS: Record<keyof ChartTokens, string> = {
  fg1: '--fg-1', fg2: '--fg-2', fg3: '--fg-3', line1: '--line-1', line2: '--line-2', line3: '--line-3', bg1: '--bg-1', bg3: '--bg-3',
  model: '--s-model', acct: '--s-acct', bench: '--s-bench', neg: '--neg', negBg: '--neg-bg', pos: '--pos', warn: '--warn', danger: '--danger', info: '--info',
  dangerLine: '--danger-line', warnLine: '--warn-line',
};

export function readTokens(el: Element | null): ChartTokens {
  const cs = el ? getComputedStyle(el) : null;
  const out = {} as ChartTokens;
  (Object.keys(VARS) as (keyof ChartTokens)[]).forEach((k) => {
    out[k] = (cs?.getPropertyValue(VARS[k]) || '').trim() || '#888';
  });
  return out;
}

export const FONT = 'Inter, ui-sans-serif, system-ui, sans-serif';
