import type { EChartsOption } from "echarts";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent
} from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { type ReactNode, useEffect, useRef } from "react";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  SVGRenderer
]);

export default function ChartPanel({ title, subtitle, option, children }: {
  title: string;
  subtitle?: string;
  option?: EChartsOption;
  children?: ReactNode;
}) {
  const chartRoot = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!option || !chartRoot.current) return;
    const chart = echarts.init(chartRoot.current, undefined, { renderer: "svg" });
    chart.setOption(option);
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(chartRoot.current);
    return () => {
      resizeObserver.disconnect();
      chart.dispose();
    };
  }, [option]);

  return (
    <section className="report-panel chart-panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {option && <div ref={chartRoot} className="chart-root" />}
      {children}
    </section>
  );
}
