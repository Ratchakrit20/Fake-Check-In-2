import { AlertTriangle, CheckCircle2, Clock3, Download, Images, Link2, Network } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { DashboardData, downloadDashboardReport, getDashboard } from "../api/client";

const fallback: DashboardData = { total_images: 0, related_pairs: 0, pending_jobs: 0, failed_jobs: 0, images_in_system: 0, reused_images: 0, total_jobs: 0, reused_jobs: 0, duplicate_jobs: [] };

function Donut({ value, total, label }: { value: number; total: number; label: string }) {
  const percent = total > 0 ? Math.min(100, Math.round(value / total * 100)) : 0;
  return <div className="dashboard-donut-wrap"><div className="dashboard-donut" style={{ "--percent": `${percent}%` } as React.CSSProperties}><div><strong>{percent}%</strong><span>{label}</span></div></div><small>{value.toLocaleString()} จาก {total.toLocaleString()}</small></div>;
}

export function Dashboard() {
  const [data, setData] = useState(fallback);
  const [totalImages, setTotalImages] = useState(() => Number(localStorage.getItem("report-total-images") || 0));
  useEffect(() => {
    let active = true;
    const load = () => getDashboard().then(result => {
      if (!active) return;
      setData(result);
      setTotalImages(current => current || result.images_in_system);
    }).catch(() => undefined);
    void load();
    const timer = window.setInterval(load, 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  useEffect(() => { localStorage.setItem("report-total-images", String(totalImages)); }, [totalImages]);
  const safeTotal = Math.max(totalImages, data.images_in_system);
  const cards = useMemo(() => [
    ["ภาพในระบบ", data.images_in_system, Images, "blue"], ["ภาพที่ใช้ซ้ำ", data.reused_images, Link2, "violet"],
    ["งานทั้งหมด", data.total_jobs, Network, "teal"], ["งานที่ใช้ภาพซ้ำ", data.reused_jobs, AlertTriangle, "amber"],
    ["งานที่รอ", data.pending_jobs, Clock3, "amber"], ["วิเคราะห์แล้ว", Math.max(0, data.total_images - data.pending_jobs), CheckCircle2, "green"],
  ] as const, [data]);
  return <section><header className="page-head"><div><p className="eyebrow">ศูนย์ตรวจสอบหลักฐานภาพ</p><h1>ภาพรวมระบบ</h1><p>ข้อมูลจะอัปเดตจากผลประมวลผลล่าสุดอัตโนมัติทุก 10 วินาที</p></div><div className="live"><span />LIVE</div></header>
    <div className="metric-grid">{cards.map(([label, value, Icon, color]) => <article className="metric" key={label}><div className={`metric-icon ${color}`}><Icon size={21} /></div><span>{label}</span><strong>{value.toLocaleString()}</strong></article>)}</div>
    <div className="dashboard-report-grid">
      <section className="panel dashboard-chart-panel"><div className="panel-head"><div><h2>สัดส่วนภาพ</h2><p>ภาพทั้งหมดเป็นข้อมูลที่อยู่ในคลัง</p></div></div><label className="manual-total"><span>ภาพทั้งหมด</span><input type="number" min={data.images_in_system} value={totalImages} onChange={event => setTotalImages(Number(event.target.value) || 0)} /></label><Donut value={data.reused_images} total={safeTotal} label="ใช้ภาพซ้ำ" /><div className="dashboard-legend"><span>ในระบบ <b>{data.images_in_system.toLocaleString()}</b></span><span>ใช้ซ้ำ <b>{data.reused_images.toLocaleString()}</b></span></div></section>
      <section className="panel dashboard-chart-panel"><div className="panel-head"><div><h2>สัดส่วนงาน</h2></div></div><Donut value={data.reused_jobs} total={data.total_jobs} label="งานใช้ภาพซ้ำ" /><div className="dashboard-legend"><span>งานทั้งหมด <b>{data.total_jobs.toLocaleString()}</b></span><span>พบใช้ซ้ำ <b>{data.reused_jobs.toLocaleString()}</b></span></div><button className="report-download" onClick={() => downloadDashboardReport(safeTotal)}><Download size={17} /> ดาวน์โหลด Excel ล่าสุด</button></section>
    </div>
    <section className="panel duplicate-job-panel"><div className="panel-head"><div><h2>เลขงานที่พบการใช้ภาพซ้ำ</h2><p>ใช้สำหรับตรวจสอบต่อและนำไปทำรายงาน</p></div><strong>{data.duplicate_jobs.length.toLocaleString()} งาน</strong></div>{data.duplicate_jobs.length ? <div className="duplicate-job-table"><div className="table-head"><span>เลขงาน</span><span>ภาพในระบบ</span><span>ภาพใช้ซ้ำ</span><span>หลักฐานเชื่อมโยง</span></div>{data.duplicate_jobs.map(job => <div key={job.job_number}><strong>{job.job_number}</strong><span>{job.images_in_system}</span><span>{job.reused_images}</span><span>{job.evidence_links}</span></div>)}</div> : <div className="dashboard-empty">ยังไม่พบเลขงานที่ใช้ภาพซ้ำ</div>}</section>
    <div className="panel"><div className="panel-head"><div><h2>ลำดับการวิเคราะห์</h2><p>คัดกรองเร็วด้วยลายนิ้วมือภาพ แล้วใช้เรขาคณิตยืนยันเฉพาะคู่ที่น่าสงสัย</p></div></div><div className="pipeline">{["SHA-256", "pHash", "SSCD", "FAISS", "SIFT", "RANSAC", "Body Verify"].map((item, i) => <div key={item}><span>{String(i + 1).padStart(2, "0")}</span><strong>{item}</strong></div>)}</div></div>
  </section>;
}
