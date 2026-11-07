import { useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, LineChart, CandlestickChart } from 'echarts/charts';
import { AriaComponent, DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsCoreOption } from 'echarts/core';
echarts.use([BarChart, LineChart, CandlestickChart, AriaComponent, DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, CanvasRenderer]);
export default function Chart({ option, theme, title }: { option: EChartsCoreOption; theme: string; title: string }) {
  const node = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!node.current) return;
    const chart = echarts.init(node.current, theme === 'dark' ? 'dark' : undefined);
    chart.setOption({ ...option, backgroundColor: 'transparent', aria: { enabled: true } });
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(node.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [option, theme]);
  return <div role="img" aria-label={title}><div className="chart" ref={node} /></div>;
}
