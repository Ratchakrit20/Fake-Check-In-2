import { Images, Link2, LoaderCircle, RefreshCw } from "lucide-react";
import { CSSProperties, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getGroups, ImageGroup, RelationshipSubgroup } from "../api/client";

const classificationNames: Record<string, string> = {
  exact_file: "ไฟล์เดียวกัน 100%", same_image: "ภาพเดียวกันแต่ไฟล์ต่างกัน",
  edited_or_cropped: "ภาพเดิมถูกดัดแปลง", background_replaced: "สงสัยเปลี่ยนฉาก",
  same_scene_new_capture: "พบฉากหลังสอดคล้องกัน", repeated_checkin: "พบคนและฉากเชื่อมโยงกัน",
};

function Subgroup({ subgroup }: { subgroup: RelationshipSubgroup }) {
  const navigate = useNavigate();
  const [highlightedPair, setHighlightedPair] = useState<{ first: string; second: string } | null>(null);
  return <section className="relationship-subgroup">
    <div className="subgroup-title"><div><p className="eyebrow">กลุ่มย่อย #{subgroup.id}</p><h3>{subgroup.size} ภาพที่เชื่อมโยงกัน</h3></div><span><Link2 size={15}/>{subgroup.relationships.length} คู่</span></div>
    <div className="group-gallery">{subgroup.images.map(image => <figure className={image.id === highlightedPair?.first ? "related-first" : image.id === highlightedPair?.second ? "related-second" : ""} key={image.id}><img src={image.url} alt={image.filename} loading="lazy"/><figcaption><strong title={image.filename}>{image.filename}</strong><small>{image.width} × {image.height}</small></figcaption></figure>)}</div>
    <div className="relation-list"><h4>ความสัมพันธ์ภายในกลุ่มย่อย</h4>{subgroup.relationships.map((relation, index) => {
      const first = subgroup.images.find(image => image.id === relation.image_a_id);
      const second = subgroup.images.find(image => image.id === relation.image_b_id);
      const showPair = () => setHighlightedPair({ first: relation.image_a_id, second: relation.image_b_id });
      return <button type="button" key={`${relation.image_a_id}-${relation.image_b_id}`} onMouseEnter={showPair} onMouseLeave={() => setHighlightedPair(null)} onFocus={showPair} onBlur={() => setHighlightedPair(null)} onClick={() => navigate(`/compare?imageA=${encodeURIComponent(relation.image_a_id)}&imageB=${encodeURIComponent(relation.image_b_id)}`)} aria-label={`เปรียบเทียบ ${first?.filename ?? "ภาพแรก"} กับ ${second?.filename ?? "ภาพที่สอง"}`}><span>{index + 1}</span><p><strong className="relation-name-first" title={first?.filename}>{first?.filename}</strong><small>เชื่อมโยงกับ</small><strong className="relation-name-second" title={second?.filename}>{second?.filename}</strong></p><em>{classificationNames[relation.classification] ?? relation.classification}</em><b>{Math.round(relation.score * 100)}%</b></button>;
    })}</div>
  </section>;
}

export function Groups() {
  const [groups, setGroups] = useState<ImageGroup[]>([]), [selected, setSelected] = useState<ImageGroup | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const detailRef = useRef<HTMLDivElement>(null);
  const [detailHeight, setDetailHeight] = useState(0);
  async function load() {
    setLoading(true); setError("");
    try { const response = await getGroups(); setGroups(response.groups); setSelected(current => response.groups.find(group => group.id === current?.id) ?? response.groups[0] ?? null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "โหลดข้อมูลไม่สำเร็จ"); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  useLayoutEffect(() => {
    const detail = detailRef.current;
    if (!detail) return;
    const updateHeight = () => setDetailHeight(detail.getBoundingClientRect().height);
    updateHeight();
    const observer = new ResizeObserver(updateHeight);
    observer.observe(detail);
    return () => observer.disconnect();
  }, [selected]);
  return <section><header className="page-head"><div><p className="eyebrow">Relationship graph</p><h1>กลุ่มภาพที่มีความสัมพันธ์กัน</h1><p>รวมกลุ่มใหญ่ตามเลขงานหลัง home_ หรือ splitter_ และแสดงความสัมพันธ์จริงเป็นกลุ่มย่อย</p></div><button className="refresh" onClick={load}><RefreshCw size={17}/> โหลดใหม่</button></header>
    {error && <div className="error">{error}</div>}
    {loading ? <div className="group-empty panel"><LoaderCircle className="spin"/><p>กำลังโหลดกลุ่มภาพ...</p></div> : groups.length === 0 ? <div className="group-empty panel"><Images size={42}/><h2>ยังไม่พบกลุ่มภาพที่ใช้ซ้ำ</h2><p>เมื่อวิเคราะห์แบบ Batch เสร็จ กลุ่มที่ตรวจพบจะแสดงที่หน้านี้</p></div> : <div className="groups-layout"><aside className="group-list panel" style={{ "--detail-height": `${detailHeight || window.innerHeight}px` } as CSSProperties}>{groups.map(group => <button className={selected?.id === group.id ? "active" : ""} key={group.id} onClick={() => setSelected(group)}><span>{group.source_ids.length === 1 ? `เลขงาน ${group.source_ids[0]}` : `กลุ่มใหญ่ #${group.id}`}</span><strong>{group.size} ภาพ · {group.subgroups.length} กลุ่มย่อย</strong><small>{group.relationship_count} ความสัมพันธ์{group.source_ids.length > 1 ? ` · ${group.source_ids.length} เลขงาน` : ""}</small></button>)}</aside>
      {selected && <div className="group-detail" ref={detailRef}><div className="group-title"><div><p className="eyebrow">{selected.source_ids.length ? `เลขงาน ${selected.source_ids.join(", ")}` : `กลุ่มใหญ่ #${selected.id}`}</p><h2>{selected.size} ภาพใน {selected.subgroups.length} กลุ่มย่อย</h2></div><span><Link2 size={16}/>{selected.relationship_count} คู่</span></div>{selected.subgroups.map(subgroup => <Subgroup key={subgroup.id} subgroup={subgroup}/>)}</div>}
    </div>}
  </section>;
}
