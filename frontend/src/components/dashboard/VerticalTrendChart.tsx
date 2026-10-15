import { formatDisplayDate } from "../../utils/date";

export type TrendPoint = { date: string; primary: number; secondary: number };

type VerticalTrendChartProps = { points: TrendPoint[]; primaryLabel: string; secondaryLabel: string };

export function VerticalTrendChart({ points, primaryLabel, secondaryLabel }: VerticalTrendChartProps) {
  if (!points.length) return <div className="insight-empty">ไม่มีข้อมูลตามช่วงวันที่ที่เลือก</div>;
  const visible = points.slice(-14);
  const maxValue = Math.max(1, ...visible.flatMap((point) => [point.primary, point.secondary]));
  const width = 760, height = 290, top = 30, right = 26, bottom = 58, left = 38;
  const chartHeight = height - top - bottom, chartWidth = width - left - right;
  const columnWidth = chartWidth / visible.length, barWidth = Math.min(22, columnWidth * 0.28);
  const trend = visible.map((point, index) => `${left + columnWidth * index + columnWidth / 2},${top + chartHeight - (point.secondary / maxValue) * chartHeight}`).join(" ");
  return (
    <div className="vertical-trend-chart" role="img" aria-label={`${primaryLabel} และ ${secondaryLabel} รายวัน`}>
      <div className="chart-legend"><span><i className="legend-primary" />{primaryLabel}</span><span><i className="legend-secondary" />{secondaryLabel} / เส้นเทรนด์</span></div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        {[0, 0.5, 1].map((ratio) => { const y = top + chartHeight - chartHeight * ratio; return <line key={ratio} x1={left} x2={width - right} y1={y} y2={y} className="chart-grid" />; })}
        {visible.map((point, index) => {
          const centerX = left + columnWidth * index + columnWidth / 2;
          const primaryHeight = (point.primary / maxValue) * chartHeight, secondaryHeight = (point.secondary / maxValue) * chartHeight;
          return <g key={point.date}>
            <rect className="chart-bar-primary" x={centerX - barWidth - 2} y={top + chartHeight - primaryHeight} width={barWidth} height={primaryHeight} rx="3" />
            <rect className="chart-bar-secondary" x={centerX + 2} y={top + chartHeight - secondaryHeight} width={barWidth} height={secondaryHeight} rx="3" />
            <text className="chart-value-primary" x={centerX - barWidth / 2 - 2} y={top + chartHeight - primaryHeight - 6}>{point.primary.toLocaleString()}</text>
            <text className="chart-value-secondary" x={centerX + barWidth / 2 + 2} y={top + chartHeight - secondaryHeight - 6}>{point.secondary.toLocaleString()}</text>
            <text className="chart-label" x={centerX} y={height - 24}>{formatDisplayDate(point.date)?.slice(0, 5) ?? point.date}</text>
          </g>;
        })}
        <polyline className="chart-trend-line" points={trend} />
      </svg>
    </div>
  );
}
