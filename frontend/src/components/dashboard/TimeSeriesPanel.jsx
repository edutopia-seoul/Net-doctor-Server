import { useMemo } from 'react';
import { curveMonotoneX } from '@visx/curve';
import { AreaChart, Area } from '@/components/charts/area-chart';
import { LineChart, Line } from '@/components/charts/line-chart';
import { Grid } from '@/components/charts/grid';
import { XAxis } from '@/components/charts/x-axis';
import { YAxis } from '@/components/charts/y-axis';
import { ChartTooltip } from '@/components/charts/tooltip/chart-tooltip';
import { chartPoints, formatNumber, formatTime } from '@/lib/dashboard';

export default function TimeSeriesPanel({ title, description, measurements, metric, unit, color, area = false }) {
  const points = useMemo(() => chartPoints(measurements, metric), [measurements, metric]);
  const missing = measurements.length - points.length;
  const Chart = area ? AreaChart : LineChart;

  return <section className="panel chart-panel" style={{ '--series-color': color }}>
    <div className="panel-heading">
      <div><p className="eyebrow">TIME SERIES</p><h3>{title}</h3><p className="muted">{description}</p></div>
      <strong className="chart-current">{points.length ? `최근 유효 ${formatNumber(points.at(-1).value, unit)}` : '측정 없음'}</strong>
    </div>
    {points.length ? <div className="chart-frame" role="img" aria-label={`${title} 시계열 차트, 유효 측정 ${points.length}건`}>
      <Chart data={points} aspectRatio="2 / 1" animationDuration={0} yDomainTween={false}
        margin={{ top: 24, right: 24, bottom: 42, left: 52 }}>
        <Grid horizontal />
        {area
          ? <Area dataKey="value" fill="var(--series-color)" stroke="var(--series-color)" fillOpacity={0.2} animate={false} />
          : <Line dataKey="value" curve={curveMonotoneX} stroke="var(--series-color)" animate={false} fadeEdges={false} showMarkers={points.length < 12} />}
        <XAxis numTicks={4} />
        <YAxis numTicks={4} formatValue={value => Number(value.toFixed(1)).toString()} />
        <ChartTooltip showDatePill={false} content={({ point }) =>
          <div className="chart-tooltip">
            <b>측정 #{point.id}</b>
            <span>{formatTime(point.date)}</span>
            <strong>{title}: {formatNumber(point.value, unit)}</strong>
          </div>
        } />
      </Chart>
    </div> : <div className="chart-empty">표시할 유효 측정값이 없습니다.</div>}
    <div className="chart-footer">
      <span className="chart-legend"><i />{title}</span>
      <span>단위 {unit.trim()} · 유효 {points.length}건{missing > 0 ? ` · 측정 실패/결측 ${missing}건 제외` : ''}</span>
    </div>
  </section>;
}
