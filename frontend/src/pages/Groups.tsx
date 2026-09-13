import { Images, Link2, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { getGroups, ImageGroup } from "../api/client";

const classificationNames: Record<string, string> = {
  exact_file: "ไฟล์เดียวกัน 100%", same_image: "ภาพเดียวกันแต่ไฟล์ต่างกัน",
  edited_or_cropped: "ภาพเดิมถูกดัดแปลง", background_replaced: "สงสัยเปลี่ยนฉาก",
};

export function Groups() {
  const [groups, setGroups] = useState<ImageGroup[]>([]), [selected, setSelected] = useState<ImageGroup | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  async function load() {
    setLoading(true); setError("");
    try { const response = await getGroups(); setGroups(response.groups); setSelected(current => response.groups.find(group => group.id === current?.id) ?? response.groups[0] ?? null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "โหลดข้อมูลไม่สำเร็จ"); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  return <section><header className="page-head"><div><p className="eyebrow">Relationship graph</p><h1>กลุ่มภาพที่มีความสัมพันธ์กัน</h1><p>แสดงเฉพาะกลุ่มที่เข้าข่ายใช้ภาพเดิม ไม่รวมแค่คนคล้ายหรือสถานที่เดิม</p></div><button className="refresh" onClick={load}><RefreshCw size={17}/> โหลดใหม่</button></header>
    {error && <div className="error">{error}</div>}
    {loading ? <div className="group-empty panel"><LoaderCircle className="spin"/><p>กำลังโหลดกลุ่มภาพ...</p></div> : groups.length === 0 ? <div className="group-empty panel"><Images size={42}/><h2>ยังไม่พบกลุ่มภาพที่ใช้ซ้ำ</h2><p>เมื่อวิเคราะห์แบบ Batch เสร็จ กลุ่มที่ตรวจพบจะแสดงที่หน้านี้</p></div> : <div className="groups-layout"><aside className="group-list panel">{groups.map(group => <button className={selected?.id === group.id ? "active" : ""} key={group.id} onClick={() => setSelected(group)}><span>กลุ่ม #{group.id}</span><strong>{group.size} ภาพ</strong><small>{group.relationships.length} ความสัมพันธ์</small></button>)}</aside>
      {selected && <div className="group-detail"><div className="group-title"><div><p className="eyebrow">กลุ่ม #{selected.id}</p><h2>{selected.size} ภาพที่เกี่ยวข้องกัน</h2></div><span><Link2 size={16}/>{selected.relationships.length} คู่</span></div><div className="group-gallery">{selected.images.map(image => <figure key={image.id}><img src={image.url} alt={image.filename} loading="lazy"/><figcaption><strong>{image.filename}</strong><small>{image.width} × {image.height}</small></figcaption></figure>)}</div><div className="relation-list"><h3>ความสัมพันธ์ภายในกลุ่ม</h3>{selected.relationships.map((relation, index) => { const first = selected.images.find(image => image.id === relation.image_a_id), second = selected.images.find(image => image.id === relation.image_b_id); return <div key={`${relation.image_a_id}-${relation.image_b_id}`}><span>{index + 1}</span><p><strong>{first?.filename}</strong><small>เชื่อมโยงกับ</small><strong>{second?.filename}</strong></p><em>{classificationNames[relation.classification] ?? relation.classification}</em><b>{Math.round(relation.score * 100)}%</b></div>; })}</div></div>}
    </div>}
  </section>;
}
