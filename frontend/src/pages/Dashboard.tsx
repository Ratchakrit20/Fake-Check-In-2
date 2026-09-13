import { AlertTriangle, CheckCircle2, Clock3, Images, Link2, Network } from "lucide-react";
import { useEffect, useState } from "react";
import { getDashboard } from "../api/client";

const fallback = { total_images: 0, related_pairs: 0, pending_jobs: 0, failed_jobs: 0 };

export function Dashboard() {
  const [data, setData] = useState(fallback);
  useEffect(() => { getDashboard().then(setData).catch(() => undefined); }, []);
  const cards = [
    ["ภาพทั้งหมด", data.total_images, Images, "blue"], ["คู่ภาพสัมพันธ์", data.related_pairs, Link2, "violet"],
    ["กลุ่มที่ตรวจพบ", 0, Network, "teal"], ["งานที่รอ", data.pending_jobs, Clock3, "amber"],
    ["วิเคราะห์แล้ว", Math.max(0, data.total_images - data.pending_jobs), CheckCircle2, "green"], ["ล้มเหลว", data.failed_jobs, AlertTriangle, "red"],
  ] as const;
  return <section><header className="page-head"><div><p className="eyebrow">ศูนย์ตรวจสอบหลักฐานภาพ</p><h1>ภาพรวมระบบ</h1><p>ตรวจหาภาพซ้ำ ภาพดัดแปลง และความสัมพันธ์ด้วยหลักฐานหลายรูปแบบ</p></div><div className="live"><span/>LIVE</div></header>
    <div className="metric-grid">{cards.map(([label, value, Icon, color]) => <article className="metric" key={label}><div className={`metric-icon ${color}`}><Icon size={21}/></div><span>{label}</span><strong>{value.toLocaleString()}</strong></article>)}</div>
    <div className="panel"><div className="panel-head"><div><h2>ลำดับการวิเคราะห์</h2><p>สัญญาณราคาถูกก่อน แล้วตรวจเชิงลึกเฉพาะภาพผู้สมัคร</p></div></div><div className="pipeline">{["SHA-256", "pHash", "DINOv2", "Vector Search", "SIFT", "RANSAC", "Score Fusion"].map((item, i) => <div key={item}><span>{String(i + 1).padStart(2, "0")}</span><strong>{item}</strong></div>)}</div></div>
  </section>;
}

