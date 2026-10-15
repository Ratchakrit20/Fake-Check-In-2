type DonutChartProps = {
  value: number;
  total: number;
  label: string;
  detail?: string;
};

export function DonutChart({ value, total, label, detail }: DonutChartProps) {
  const percent = total > 0 ? Math.min(100, Math.round((value / total) * 100)) : 0;
  return (
    <div className="dashboard-donut-wrap">
      <div className="dashboard-donut" style={{ "--percent": `${percent}%` } as React.CSSProperties}>
        <div><strong>{percent}%</strong><span>{label}</span></div>
      </div>
      <small>{detail ?? `${value.toLocaleString()} จาก ${total.toLocaleString()}`}</small>
    </div>
  );
}
