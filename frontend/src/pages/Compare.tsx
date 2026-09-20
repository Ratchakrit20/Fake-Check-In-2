import { Image as ImageIcon, LoaderCircle, ScanSearch, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { compareImages, getStoredImageFile, RelationshipResult } from "../api/client";
import { FileDrop } from "../components/FileDrop";

const evidenceLabels: Record<string, string> = {
  exact_duplicate: "ไฟล์ตรงกันทุกไบต์",
  phash_distance: "ความต่างของภาพโดยรวม",
  phash_normal_distance: "ความต่างเมื่อวางภาพปกติ",
  phash_flip_distance: "ความต่างเมื่อลองกลับภาพ",
  phash_rotation_distances: "ความต่างเมื่อลองหมุนภาพ",
  phash_max_distance: "ค่าความต่างสูงสุด",
  embedding_similarity: "ความคล้ายเชิงสำเนาจาก SSCD",
  sift_good_matches: "จุดภาพที่ตรงกัน",
  sift_reference_features: "จุดอ้างอิงที่พบ",
  ransac_inliers: "จุดที่ยืนยันตำแหน่งได้",
  ransac_inlier_ratio: "สัดส่วนพื้นที่ที่สอดคล้อง",
  flip_detected: "ตรวจพบการกลับภาพ",
  rotation_degrees: "องศาที่หมุนเพื่อจัดแนวภาพ",
  detected_transform: "รูปแบบการเปลี่ยนแปลง",
  scene_change_suspected: "อาจมีการเปลี่ยนฉาก",
  body_reuse_gate: "อวัยวะหลักยืนยันการใช้ภาพซ้ำ",
  body_reuse_suspected: "อวัยวะหนึ่งส่วนเข้าข่ายถูกใช้ซ้ำ",
  similar_person_only: "พบเฉพาะใบหน้า/ลำคอที่คล้าย",
  body_part_inliers: "จุดตรงกันแยกตามอวัยวะ",
  foreground_ransac_inliers: "จุดยืนยันบนตัวบุคคล",
  foreground_ransac_ratio: "สัดส่วนจุดถูกต้องบนตัวบุคคล",
  foreground_coverage: "พื้นที่ตัวบุคคลที่ยืนยันได้",
  foreground_source_reuse: "ยืนยันการนำ foreground เดิมมาใช้",
  repeated_checkin_suspected: "สงสัยเช็กอินซ้ำด้วยคนและสถานที่เดิม",
  background_ransac_inliers: "จุดยืนยันบนฉากหลัง",
  background_ransac_ratio: "สัดส่วนจุดถูกต้องบนฉากหลัง",
  background_coverage: "พื้นที่ฉากหลังที่ยืนยันได้",
  same_location_suspected: "ตรวจพบสถานที่เดิมข้ามงาน",
  ransac_coverage: "พื้นที่ภาพเดิมที่ยืนยันได้",
  recapture_suspected: "สงสัยถ่ายซ้ำจากหน้าจอ",
  blur_variance_a: "ความคมชัดภาพ A",
  blur_variance_b: "ความคมชัดภาพ B",
  blurred_crop_suspected: "ตรวจพบภาพเบลอหรือครอปจากภาพเดิม",
  whole_image_fallback_used: "ใช้อัตราตรงกันทั้งภาพแทนอวัยวะที่ตรวจไม่ครบ",
  heatmap_foreground_change: "พื้นที่เปลี่ยนบนตัวบุคคลหลังจัดแนว",
  heatmap_background_change: "พื้นที่เปลี่ยนบนฉากหลังหลังจัดแนว",
  heatmap_used_for_decision: "นำ heatmap ไปตัดสินอัตโนมัติ",
};

function thaiConclusion(result: RelationshipResult): { title: string; detail: string } {
  const evidence = result.evidence;
  if (result.classification === "exact_file") {
    return { title: "เป็นไฟล์เดียวกัน", detail: "ข้อมูลของทั้งสองไฟล์ตรงกันทั้งหมด แม้ชื่อไฟล์อาจต่างกัน" };
  }
  if (evidence.flip_detected === true || evidence.detected_transform === "horizontal_flip") {
    return { title: "ภาพเดิมถูกกลับด้าน", detail: "พบจุดสำคัญชุดเดียวกันหลังกลับภาพในแนวนอน" };
  }
  if (typeof evidence.rotation_degrees === "number" && evidence.rotation_degrees !== 0) {
    return { title: `ภาพเดิมถูกหมุน ${evidence.rotation_degrees}°`, detail: "พบจุดสำคัญชุดเดียวกันหลังหมุนภาพกลับมาจัดแนว" };
  }
  if (evidence.recapture_suspected === true) {
    return { title: "เข้าข่ายถ่ายภาพเดิมซ้ำผ่านหน้าจอหรืออุปกรณ์อีกเครื่อง", detail: "แม้สี ความคม และลายพิกเซลเปลี่ยนไป แต่โครงสร้างของภาพเดิมตรงกันเป็นบริเวณกว้าง" };
  }
  if (evidence.blurred_crop_suspected === true) {
    return { title: "เข้าข่ายภาพเดิมที่ถูกทำให้เบลอหรือครอบตัด", detail: "แม้รายละเอียดภาพหายไป แต่ยังพบจุดสำคัญที่สอดคล้องกันทางเรขาคณิตและเนื้อหาหลักยังตรงกัน" };
  }
  if (result.classification === "background_replaced") {
    return { title: "พบบริเวณบุคคลเดิม แต่ฉากหลังแตกต่าง", detail: "จุดบนบริเวณบุคคลสอดคล้องกันทางเรขาคณิต ขณะที่หลักฐานจากฉากหลังไม่เพียงพอ จึงควรตรวจสอบว่าอาจมีการเปลี่ยนฉาก" };
  }
  if (result.classification === "same_image") {
    return { title: "เป็นภาพเดียวกัน แต่ไฟล์ต่างกัน", detail: "ภาพที่เห็นตรงกัน แต่อาจถูกบีบอัด ย่อ หรือบันทึกเป็นไฟล์ใหม่" };
  }
  if (result.classification === "similar_person") {
    return { title: "พบบุคคลคล้ายกัน แต่ยังยืนยันว่าใช้ภาพเดิมไม่ได้", detail: "พบความคล้ายบริเวณศีรษะหรือลำคอ แต่หลักฐานจากลำตัว แขน และขายังไม่เพียงพอ" };
  }
  if (result.classification === "edited_or_cropped") {
    return { title: "ภาพเดิมถูกดัดแปลง", detail: "พบหลักฐานว่าภาพมาจากแหล่งเดียวกัน เช่น ย่อ ขยาย ครอป หมุน ปรับสี หรือบีบอัดใหม่" };
  }
  if (result.classification === "same_scene_new_capture") {
    return { title: "พบรายละเอียดฉากหลังที่สอดคล้องกัน", detail: "จุดบริเวณฉากหลังผ่านการตรวจตำแหน่งทางเรขาคณิต แต่อาจเป็นสถานที่เดิม ลวดลายคล้ายกัน หรือภาพถ่ายคนละเวลา จึงต้องตรวจสอบเพิ่มเติม" };
  }
  if (result.classification === "repeated_checkin") {
    return { title: "พบจุดสอดคล้องทั้งบริเวณบุคคลและฉากหลัง", detail: "ระบบพบหลักฐานแยกกันในโซนบุคคลและโซนที่จัดเป็นฉากหลัง ผลนี้ยังไม่ยืนยันว่าสถานที่เดียวกัน จึงควรเปิดภาพหลักฐานและตรวจสอบประวัติงาน" };
  }
  return { title: "ไม่พบว่าเป็นภาพเดียวกัน", detail: "หลักฐานที่ตรวจพบยังไม่แสดงความสัมพันธ์ที่ชัดเจน" };
}

const verdictText = {
  reused: { label: "เข้าข่ายใช้ภาพเดิม", hint: "ระบบพบหลักฐานเพียงพอว่ามีการนำภาพเดิมกลับมาใช้", icon: "!" },
  review: { label: "ควรตรวจสอบโดยเจ้าหน้าที่", hint: "พบสัญญาณการใช้ภาพเดิมบางส่วน แต่ยังไม่ควรตัดสินอัตโนมัติ", icon: "?" },
  not_reused: { label: "ยังไม่เข้าข่ายใช้ภาพเดิม", hint: "หลักฐานไม่เพียงพอที่จะยืนยันว่ามีการนำภาพเดิมมาใช้", icon: "✓" },
} as const;

function evidenceTransformLabel(evidence: Record<string, unknown>): string {
  if (evidence.detected_transform === "horizontal_flip" || evidence.flip_detected === true) {
    return "ภาพ B ถูกกลับด้านแนวนอนเพื่อจัดแนว";
  }
  if (typeof evidence.rotation_degrees === "number" && evidence.rotation_degrees !== 0) {
    return `ภาพ B ถูกหมุน ${evidence.rotation_degrees}° เพื่อจัดแนว`;
  }
  return "ภาพต้นฉบับไม่ต้องปรับแนว";
}

function displayValue(key: string, value: unknown): string {
  if (key === "body_part_inliers" && typeof value === "object" && value !== null) {
    const labels: Record<string, string> = { foot: "เท้า", hand: "มือ", head: "ศีรษะ", larm: "แขนท่อนล่าง", lleg: "ขาท่อนล่าง", neck: "คอ", torso: "ลำตัว", uarm: "แขนท่อนบน", uleg: "ขาท่อนบน" };
    return Object.entries(value as Record<string, number>).map(([name, count]) => `${labels[name] ?? name} ${count}`).join(", ") || "ไม่พบ";
  }
  if (key === "phash_rotation_distances" && typeof value === "object" && value !== null) {
    const labels: Record<string, string> = { rotate_90: "90°", rotate_180: "180°", rotate_270: "270°" };
    return Object.entries(value as Record<string, number>)
      .map(([name, distance]) => `${labels[name] ?? name}: ${distance}`)
      .join(", ");
  }
  if (typeof value === "boolean") return value ? "ใช่" : "ไม่ใช่";
  if (key.includes("similarity") || key.includes("ratio") || key.includes("_change")) return `${(Number(value) * 100).toFixed(1)}%`;
  return String(value).replace("horizontal_flip", "กลับด้านแนวนอน").replace("original", "ภาพปกติ");
}

function plainReasons(result: RelationshipResult): string[] {
  const e = result.evidence;
  const reasons: string[] = [];
  if (e.exact_duplicate === true) reasons.push("ข้อมูลภายในไฟล์ตรงกันทั้งหมด จึงยืนยันได้ว่าเป็นไฟล์เดียวกัน");
  if (e.flip_detected === true) reasons.push("เมื่อลองกลับภาพแนวนอนแล้ว รายละเอียดสำคัญตรงกับภาพต้นฉบับ");
  if (typeof e.rotation_degrees === "number" && e.rotation_degrees !== 0) reasons.push(`เมื่อหมุนภาพกลับ ${e.rotation_degrees}° แล้ว รายละเอียดสำคัญและตำแหน่งตรงกับภาพต้นฉบับ`);
  if (e.recapture_suspected === true) reasons.push("โครงสร้างภาพตรงกันเป็นบริเวณกว้าง แม้ความคมหรือลายพิกเซลเปลี่ยนจากการถ่ายผ่านอีกหน้าจอ");
  if (e.blurred_crop_suspected === true) reasons.push("ยังพบรายละเอียดชุดเดิมหลังภาพถูกทำให้เบลอหรือครอบตัด");
  if (e.whole_image_fallback_used === true) reasons.push("โมเดลอวัยวะตรวจได้ไม่ครบ จึงยืนยันเพิ่มด้วยจุดตรงกันที่กระจายทั่วภาพ");
  if (e.body_reuse_gate === true) reasons.push("พบตำแหน่งบนร่างกายหลายส่วนตรงกันมากพอ จึงมีแนวโน้มว่านำคนจากภาพเดิมมาใช้");
  else if (e.body_reuse_suspected === true) reasons.push("พบอวัยวะบางส่วนตรงกัน แต่ควรตรวจด้วยสายตาเพิ่มเติม");
  if (typeof e.embedding_similarity === "number") reasons.push(`AI ประเมินว่าเนื้อหาโดยรวมคล้ายกัน ${(e.embedding_similarity * 100).toFixed(0)}%`);
  if (typeof e.ransac_inliers === "number") reasons.push(`พบรายละเอียดที่ตรงกันและยืนยันตำแหน่งได้ ${e.ransac_inliers} จุด`);
  if (!reasons.length) reasons.push("ระบบยังไม่พบหลักฐานที่ชัดเจนพอจะยืนยันว่ามีการนำภาพเดิมกลับมาใช้");
  return reasons.slice(0, 4);
}

function technologyEvidence(result: RelationshipResult) {
  const e = result.evidence;
  const phashDistance = typeof e.phash_distance === "number" ? e.phash_distance : null;
  const sscd = typeof e.embedding_similarity === "number" ? e.embedding_similarity : null;
  const sift = typeof e.sift_good_matches === "number" ? e.sift_good_matches : 0;
  const inliers = typeof e.ransac_inliers === "number" ? e.ransac_inliers : 0;
  return [
    { name: "pHash", detail: "ลายนิ้วมือภาพโดยรวม", passed: e.exact_duplicate === true || (phashDistance !== null && phashDistance <= 10), value: phashDistance === null ? "ไม่มีค่า" : `ต่าง ${phashDistance} จาก 64 จุด`, view: result.visualizations?.aligned_pair ? "aligned" as const : "compare" as const },
    { name: "SSCD", detail: "ลายนิ้วมือสำหรับตรวจภาพที่ถูกคัดลอกหรือดัดแปลง", passed: sscd !== null && sscd >= .65, value: sscd === null ? "ไม่มีค่า" : `คล้ายเชิงสำเนา ${(sscd * 100).toFixed(0)}%`, view: result.visualizations?.aligned_pair ? "aligned" as const : "compare" as const },
    { name: "SIFT + RANSAC", detail: "รายละเอียดและตำแหน่งที่ตรงกันจริง", passed: sift >= 12 && inliers >= 8, value: `ตรง ${sift} จุด ยืนยันตำแหน่ง ${inliers} จุด`, view: "matches" as const },
    { name: "โมเดลแยกอวัยวะ", detail: "ตรวจส่วนของคนที่อาจถูกนำมาใช้ซ้ำ", passed: e.body_reuse_gate === true || e.body_reuse_suspected === true || e.similar_person_only === true, value: e.body_reuse_gate === true ? "หลายส่วนของร่างกายตรงกัน" : e.body_reuse_suspected === true ? "พบอวัยวะบางส่วนตรงกัน" : e.similar_person_only === true ? "พบศีรษะหรือคอคล้ายกัน" : "ยังไม่เข้าเกณฑ์", view: "body" as const },
    { name: "พื้นที่ที่เปลี่ยนไป", detail: "เปรียบเทียบความเปลี่ยนแปลงบนตัวบุคคลและฉากหลังหลังวางภาพให้ตรงกัน", passed: Boolean(result.visualizations?.change_heatmap), status: e.heatmap_used_for_decision === true ? "ใช้ช่วยยืนยันผล" : "ใช้ประกอบการตรวจสอบ", value: typeof e.heatmap_foreground_change === "number" && typeof e.heatmap_background_change === "number" ? `คนเปลี่ยน ${(e.heatmap_foreground_change * 100).toFixed(0)}% · ฉากเปลี่ยน ${(e.heatmap_background_change * 100).toFixed(0)}%` : "สร้างไม่ได้เพราะภาพวางตรงกันไม่เพียงพอ", view: "heatmap" as const },
  ];
}

export function Compare() {
  const [searchParams] = useSearchParams();
  const imageAId = searchParams.get("imageA"), imageBId = searchParams.get("imageB");
  const loadedPair = useRef("");
  const [first, setFirst] = useState<File | null>(null), [second, setSecond] = useState<File | null>(null);
  const [result, setResult] = useState<RelationshipResult | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<"a" | "b" | "compare" | "aligned" | "matches" | "body" | "heatmap" | null>(null);
  const firstUrl = useMemo(() => first ? URL.createObjectURL(first) : "", [first]);
  const secondUrl = useMemo(() => second ? URL.createObjectURL(second) : "", [second]);
  useEffect(() => () => { if (firstUrl) URL.revokeObjectURL(firstUrl); }, [firstUrl]);
  useEffect(() => () => { if (secondUrl) URL.revokeObjectURL(secondUrl); }, [secondUrl]);
  useEffect(() => {
    if (!imageAId || !imageBId) return;
    const pairKey = `${imageAId}:${imageBId}`;
    if (loadedPair.current === pairKey) return;
    loadedPair.current = pairKey;
    let active = true;
    setLoading(true); setError(""); setResult(null);
    void Promise.all([getStoredImageFile(imageAId), getStoredImageFile(imageBId)])
      .then(async ([storedFirst, storedSecond]) => {
        if (!active) return;
        setFirst(storedFirst); setSecond(storedSecond);
        const comparison = await compareImages(storedFirst, storedSecond);
        if (active) setResult(comparison);
      })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : "โหลดคู่ภาพไม่สำเร็จ"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [imageAId, imageBId]);
  async function run() {
    if (!first || !second) return;
    setLoading(true); setError(""); setResult(null);
    try { setResult(await compareImages(first, second)); } catch (err) { setError(err instanceof Error ? err.message : "เกิดข้อผิดพลาด"); } finally { setLoading(false); }
  }
  return <section><header className="page-head"><div><p className="eyebrow">ตรวจสอบแบบคู่</p><h1>เปรียบเทียบสองภาพ</h1><p>ระบบจะรวมหลักฐานเชิงภาพ ความหมาย และเรขาคณิตเพื่ออธิบายผล</p></div></header>
    <div className="compare-grid"><FileDrop label="ภาพ A" file={first} onChange={setFirst}/><FileDrop label="ภาพ B" file={second} onChange={setSecond}/></div>
    <button className="primary" disabled={!first || !second || loading} onClick={run}>{loading ? <LoaderCircle className="spin" size={19}/> : <ScanSearch size={19}/>} {loading ? "กำลังวิเคราะห์..." : "เริ่มวิเคราะห์ความสัมพันธ์"}</button>
    {error && <div className="error">{error}</div>}
    {result && (() => {
      const conclusion = thaiConclusion(result), verdict = verdictText[result.reuse_verdict];
      return <div className={`result-card panel verdict-${result.reuse_verdict}`}>
        <div className="verdict-banner"><span className="verdict-icon">{verdict.icon}</span><div><small>คำตัดสินเรื่องการใช้ภาพซ้ำ</small><h2>{verdict.label}</h2><p>{verdict.hint}</p></div></div>
        <div className="plain-result"><div className="score-ring" style={{"--score": `${result.score * 100}%`} as React.CSSProperties}><strong>{Math.round(result.score * 100)}</strong><span>ความสัมพันธ์</span></div><div><p className="eyebrow">ลักษณะที่ตรวจพบ</p><h3>{conclusion.title}</h3><p>{conclusion.detail}</p></div></div>
        <div className="decision-explainer">
          <div><h4>เหตุผลที่ระบบตัดสินแบบนี้</h4><ul>{plainReasons(result).map(reason => <li key={reason}>{reason}</li>)}</ul></div>
          <div className="source-images"><h4>ภาพที่นำมาตรวจ</h4><p>กดเพื่อเปิดดูภาพขนาดใหญ่</p><div><button onClick={() => setPreview("a")}><ImageIcon size={17}/><span>ภาพ A</span><small>{first?.name}</small></button><button onClick={() => setPreview("b")}><ImageIcon size={17}/><span>ภาพ B</span><small>{second?.name}</small></button></div></div>
        </div>
        <details className="technology" open><summary>หลักฐานจากแต่ละเทคโนโลยี</summary><p className="technology-hint">รายการที่ไม่ผ่านเกณฑ์จะไม่ถูกใช้ยืนยันผล แต่ยังเปิดดูภาพที่นำไปตรวจได้</p>{result.visualizations?.aligned_pair && <div className="alignment-notice"><span>ภาพ A</span><b>ต้นฉบับ</b><i>เทียบกับ</i><span>ภาพ B</span><b>{evidenceTransformLabel(result.evidence).replace("ภาพ B ถูก", "").replace("เพื่อจัดแนว", "แล้ว")}</b></div>}<div className="technology-grid">{technologyEvidence(result).map(item => { const specialized = item.view === "matches" ? result.visualizations?.sift_ransac : item.view === "body" ? result.visualizations?.body_parts : item.view === "heatmap" ? result.visualizations?.change_heatmap : item.view === "aligned" ? result.visualizations?.aligned_pair : null; const previewTarget = specialized ? item.view : result.visualizations?.aligned_pair ? "aligned" : "compare"; return <div className={item.passed ? "passed" : "not-passed"} key={item.name}><span className="tech-status">{"status" in item ? item.status : item.passed ? "ผ่านเกณฑ์" : "ไม่ผ่านเกณฑ์"}</span><strong>{item.name}</strong><span>{item.detail}</span><b>{item.value}</b><button onClick={() => setPreview(previewTarget)}><ImageIcon size={15}/> {specialized ? "ดูหลักฐานที่ใช้จริง" : "ดูภาพที่นำไปตรวจ"}</button></div>; })}</div></details>
        <details className="technical"><summary>ดูค่าตรวจสอบสำหรับผู้เชี่ยวชาญ</summary><div className="evidence">{Object.entries(result.evidence).filter(([, value]) => value !== null).map(([key, value]) => <div key={key}><span>{evidenceLabels[key] ?? key}</span><strong>{displayValue(key, value)}</strong></div>)}</div></details>
        {preview && <div className="image-modal" role="dialog" aria-modal="true" aria-label="ดูภาพเปรียบเทียบ" onClick={() => setPreview(null)}><button aria-label="ปิดภาพ"><X size={22}/></button>{preview === "compare" ? <div className="modal-comparison" onClick={event => event.stopPropagation()}><figure><img src={firstUrl} alt="ภาพ A"/><figcaption>ภาพ A — {first?.name}</figcaption></figure><figure><img src={secondUrl} alt="ภาพ B"/><figcaption>ภาพ B — {second?.name}</figcaption></figure></div> : preview === "aligned" || preview === "matches" || preview === "body" || preview === "heatmap" ? <figure onClick={event => event.stopPropagation()}><img src={preview === "aligned" ? result.visualizations.aligned_pair : preview === "matches" ? result.visualizations.sift_ransac : preview === "heatmap" ? result.visualizations.change_heatmap : result.visualizations.body_parts} alt="ภาพหลักฐาน"/><figcaption>{preview === "aligned" ? `ภาพที่ใช้วิเคราะห์ — ${evidenceTransformLabel(result.evidence)}` : preview === "matches" ? "เส้นสีเขียวคือจุดที่ SIFT พบและ RANSAC ยืนยันตำแหน่งแล้ว" : preview === "heatmap" ? "สีร้อนคือบริเวณที่เปลี่ยนหลังจัดแนว สีมืดคือพื้นที่นอกขอบเขตเปรียบเทียบ" : "สีที่ระบายคือบริเวณอวัยวะที่โมเดลตรวจพบ"}</figcaption></figure> : <figure onClick={event => event.stopPropagation()}><img src={preview === "a" ? firstUrl : secondUrl} alt={`ภาพ ${preview.toUpperCase()}`}/><figcaption>ภาพ {preview.toUpperCase()} — {preview === "a" ? first?.name : second?.name}</figcaption></figure>}</div>}
      </div>;
    })()}
  </section>;
}
