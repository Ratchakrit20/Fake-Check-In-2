type TechnicianPoint = { technician_id: string; reused_customer_ids: number };

export function TechnicianBarChart({ points }: { points: TechnicianPoint[] }) {
  const visible = points.slice(0, 10), max = Math.max(1, ...visible.map((point) => point.reused_customer_ids));
  if (!visible.length) return <div className="insight-empty">ยังไม่พบ Technician ID ที่มีภาพใช้ซ้ำ</div>;
  return <ol className="technician-bars">{visible.map((point) => <li key={point.technician_id}>
    <code>{point.technician_id}</code><div className="technician-bar-track"><span style={{ width: `${(point.reused_customer_ids / max) * 100}%` }} /></div><strong>{point.reused_customer_ids.toLocaleString()}</strong>
  </li>)}</ol>;
}
