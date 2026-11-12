import { Images, Link2, LoaderCircle, RefreshCw } from "lucide-react";
import {
  CSSProperties,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getGroups, ImageGroup, RelationshipSubgroup } from "../api/client";
import { formatDisplayDate } from "../utils/date";

const classificationNames: Record<string, string> = {
  exact_file: "ไฟล์ภาพเดียวกันทุกไบต์",
  same_image: "ภาพเดียวกัน แต่ไฟล์ต่างกัน",
  edited_or_cropped: "ภาพเดิมถูกดัดแปลง",
  background_replaced: "พบบุคคลเดิม แต่ฉากหลังต่างกัน",
  same_scene_new_capture: "พบรายละเอียดฉากหลังตรงกัน",
  repeated_checkin: "พบจุดตรงกันทั้งบุคคลและฉากหลัง",
  similar_person: "พบบุคคลคล้ายกัน",
  unrelated: "ไม่พบความสัมพันธ์",
};

const classificationOptions = [
  { key: "exact_file", title: "ไฟล์ภาพเดียวกันทุกไบต์", description: "ข้อมูลไฟล์ตรงกันด้วย SHA-256", result: "เข้าข่ายใช้ภาพเดิม" },
  { key: "same_image", title: "ภาพเดียวกัน แต่ไฟล์ต่างกัน", description: "ภาพเดียวกันที่บันทึกหรือบีบอัดใหม่", result: "เข้าข่ายใช้ภาพเดิม" },
  { key: "edited_or_cropped", title: "ภาพเดิมถูกดัดแปลง", description: "ครอป หมุน กลับด้าน เบลอ หรือแก้ไขภาพ", result: "เข้าข่ายใช้ภาพเดิม" },
  { key: "background_replaced", title: "พบบุคคลเดิม แต่ฉากหลังต่างกัน", description: "อาจนำบุคคลหรือวัตถุเดิมไปเปลี่ยนฉาก", result: "ควรตรวจสอบต่อ" },
  { key: "same_scene_new_capture", title: "พบรายละเอียดฉากหลังตรงกัน", description: "อาจเป็นสถานที่เดิม ลายคล้ายกัน หรือถ่ายคนละเวลา", result: "ควรตรวจสอบต่อ" },
  { key: "repeated_checkin", title: "พบจุดตรงกันทั้งบุคคลและฉากหลัง", description: "พบหลักฐานในทั้งสองบริเวณ แต่ยังไม่ยืนยันสถานที่", result: "ควรตรวจสอบต่อ" },
  { key: "similar_person", title: "พบบุคคลคล้ายกัน", description: "ยังยืนยันไม่ได้ว่าเป็นการใช้ภาพเดิม", result: "ยังไม่เข้าข่ายใช้ภาพเดิม" },
  { key: "unrelated", title: "ไม่พบความสัมพันธ์", description: "หลักฐานไม่ถึงเกณฑ์ว่าภาพเกี่ยวข้องกัน", result: "ยังไม่เข้าข่ายใช้ภาพเดิม" },
];

function ImageSourceMeta({ jobNumber, checkinDate }: { jobNumber: string | null; checkinDate: string | null }) {
  const date = formatDisplayDate(checkinDate);
  if (!jobNumber && !date) return null;
  return (
    <span className="image-source-meta">
      {jobNumber && <span>Job {jobNumber}</span>}
      {date && <span>Date {date}</span>}
    </span>
  );
}

function GroupContent({ group, classifications }: { group: ImageGroup; classifications: string[] | null }) {
  const navigate = useNavigate();
  const subgroups = group.subgroups
    .map((item) => ({
      ...item,
      relationships: item.relationships.filter(
        (relation) => classifications === null || classifications.includes(relation.classification),
      ),
    }))
    .filter((item) => item.relationships.length > 0);
  const usedImageIds = new Set(subgroups.flatMap((item) => item.relationships.flatMap((relation) => [relation.image_a_id, relation.image_b_id])));
  const images = Array.from(
    new Map(
      subgroups.flatMap((item) => item.images)
        .filter((image) => usedImageIds.has(image.id))
        .map((image) => [image.id, image]),
    ).values(),
  );
  const relationships = subgroups.flatMap((item: RelationshipSubgroup) => item.relationships);
  return (
    <section className="relationship-subgroup">
      <div className="group-gallery">
        {images.map((image) => (
          <figure key={image.id}>
            <img src={image.url} alt={image.filename} loading="lazy" />
            <figcaption>
              {/* <strong title={image.filename}>{image.filename}</strong> */}
              <ImageSourceMeta jobNumber={image.job_number} checkinDate={image.checkin_date} />
              <small>
                {image.width} × {image.height}
              </small>
            </figcaption>
          </figure>
        ))}
      </div>
      <div className="relation-list">
        <h4>คู่ภาพที่ระบบตรวจพบ</h4>
        {relationships.map((relation, index) => {
          const first = images.find(
            (image) => image.id === relation.image_a_id,
          );
          const second = images.find(
            (image) => image.id === relation.image_b_id,
          );
          return (
            <button
              type="button"
              key={`${relation.image_a_id}-${relation.image_b_id}`}
              onClick={() =>
                navigate(
                  `/compare?imageA=${encodeURIComponent(relation.image_a_id)}&imageB=${encodeURIComponent(relation.image_b_id)}`,
                )
              }
              aria-label={`เปรียบเทียบ ${first?.filename ?? "ภาพแรก"} กับ ${second?.filename ?? "ภาพที่สอง"}`}
            >
              <span className="relation-index">{index + 1}</span>
              <p>
                {first && <ImageSourceMeta jobNumber={first.job_number} checkinDate={first.checkin_date} />}
                <small>ใช้ภาพซ้ำกับ</small>
                {second && <ImageSourceMeta jobNumber={second.job_number} checkinDate={second.checkin_date} />}
              </p>
              <em>
                {classificationNames[relation.classification] ??
                  relation.classification}
              </em>
              {first && second && (
                <span className="relation-preview" aria-hidden="true">
                  <figure>
                    <img src={first.url} alt="" loading="lazy" />
                    <figcaption title={first.filename}>{first.filename}</figcaption>
                  </figure>
                  <figure>
                    <img src={second.url} alt="" loading="lazy" />
                    <figcaption title={second.filename}>{second.filename}</figcaption>
                  </figure>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function Groups() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [groups, setGroups] = useState<ImageGroup[]>([]),
    [selected, setSelected] = useState<ImageGroup | null>(null);
  const [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [selectedClassifications, setSelectedClassifications] = useState<string[] | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const [detailHeight, setDetailHeight] = useState(0);
  const visibleGroups = groups.filter((group) =>
    group.subgroups.some((subgroup) => subgroup.relationships.some(
      (relation) => selectedClassifications === null || selectedClassifications.includes(relation.classification),
    )),
  );
  const displayedSelected = visibleGroups.find((group) => group.id === selected?.id) ?? visibleGroups[0] ?? null;
  const visiblePairCount = visibleGroups.reduce(
    (total, group) => total + group.subgroups.reduce(
      (count, subgroup) => count + subgroup.relationships.filter(
        (relation) => selectedClassifications === null || selectedClassifications.includes(relation.classification),
      ).length,
      0,
    ),
    0,
  );
  async function load() {
    setLoading(true);
    setError("");
    try {
      const response = await getGroups();
      setGroups(response.groups);
      const requestedBbid = searchParams.get("bbid");
      const requestedGroupId = Number(searchParams.get("group"));
      const requestedBbidGroup = requestedBbid
        ? response.groups.find((group) =>
            group.source_ids.includes(requestedBbid),
          )
        : undefined;
      const nextSelected =
        requestedBbidGroup ??
        (Number.isInteger(requestedGroupId) && requestedGroupId > 0
          ? response.groups.find((group) => group.id === requestedGroupId)
          : undefined) ??
        response.groups.find((group) => group.id === selected?.id) ??
        response.groups[0] ??
        null;
      setSelected(nextSelected);
      if (requestedBbid) {
        if (requestedBbidGroup) {
          setSearchParams(
            { group: String(requestedBbidGroup.id) },
            { replace: true },
          );
        } else {
          setError(`ไม่พบกลุ่มภาพของ BBID ${requestedBbid}`);
        }
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "โหลดข้อมูลไม่สำเร็จ",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  useLayoutEffect(() => {
    const detail = detailRef.current;
    if (!detail) return;
    const updateHeight = () =>
      setDetailHeight(detail.getBoundingClientRect().height);
    updateHeight();
    const observer = new ResizeObserver(updateHeight);
    observer.observe(detail);
    return () => observer.disconnect();
  }, [displayedSelected]);
  return (
    <section>
      <header className="page-head">
        <div>
          <p className="eyebrow">ผลการตรวจสอบ</p>
          <h1>กลุ่มภาพที่ใช้ซ้ำกัน</h1>
          <p>เลือกกลุ่มเพื่อดูรูปภาพและคู่ภาพที่ระบบตรวจพบ</p>
        </div>
        <button className="refresh" onClick={load}>
          <RefreshCw size={17} /> โหลดใหม่
        </button>
      </header>
      {error && <div className="error">{error}</div>}
      {loading ? (
        <div className="group-empty panel">
          <LoaderCircle className="spin" />
          <p>กำลังโหลดกลุ่มภาพ...</p>
        </div>
      ) : groups.length === 0 ? (
        <div className="group-empty panel">
          <Images size={42} />
          <h2>ยังไม่พบกลุ่มภาพที่ใช้ซ้ำ</h2>
          <p>เมื่อวิเคราะห์แบบ Batch เสร็จ กลุ่มที่ตรวจพบจะแสดงที่หน้านี้</p>
        </div>
      ) : (
        <>
        <section className="group-classification-filter panel" aria-labelledby="group-filter-title">
          <div className="group-filter-heading">
            <div>
              <p className="eyebrow">ตัวกรองผลตรวจ</p>
              <h2 id="group-filter-title">เลือกประเภทความสัมพันธ์</h2>
              <p>เลือกประเภทที่ต้องการดู ระบบจะแสดงเฉพาะคู่ภาพประเภทนั้นในแต่ละกลุ่ม</p>
            </div>
            <div className="group-filter-summary" aria-live="polite">
              <strong>{visibleGroups.length.toLocaleString()}</strong> กลุ่ม
              <span>{visiblePairCount.toLocaleString()} คู่ภาพ</span>
            </div>
          </div>
          <div className="group-classification-options">
            <label className="group-classification-option group-classification-all">
              <input
                type="checkbox"
                checked={selectedClassifications === null}
                onChange={() => setSelectedClassifications(null)}
              />
              <span><strong>ทุกประเภท</strong><small>แสดงผลตรวจทุกประเภท</small></span>
            </label>
            {classificationOptions.map((option) => {
              const checked = selectedClassifications === null || selectedClassifications.includes(option.key);
              return (
                <label className="group-classification-option" key={option.key}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      const next = selectedClassifications === null
                        ? classificationOptions.filter((item) => item.key !== option.key).map((item) => item.key)
                        : selectedClassifications.includes(option.key)
                          ? selectedClassifications.filter((item) => item !== option.key)
                          : [...selectedClassifications, option.key];
                      setSelectedClassifications(
                        next.length === classificationOptions.length ? null : next,
                      );
                    }}
                  />
                  <span>
                    <strong>{option.title}</strong>
                    <small>{option.description}</small>
                    <em>{option.result}</em>
                  </span>
                </label>
              );
            })}
          </div>
        </section>
        {visibleGroups.length === 0 ? (
          <div className="group-empty panel">
            <Images size={42} />
            <h2>ไม่พบคู่ภาพตามประเภทที่เลือก</h2>
            <p>ลองเลือกประเภทอื่น หรือกด “ทุกประเภท” เพื่อดูผลทั้งหมด</p>
          </div>
        ) : <div className="groups-layout">
          <aside
            className="group-list panel"
            style={
              {
                "--detail-height": `${detailHeight || window.innerHeight}px`,
              } as CSSProperties
            }
          >
            {visibleGroups.map((group) => (
              <button
                className={displayedSelected?.id === group.id ? "active" : ""}
                key={group.id}
                onClick={() => {
                  setSelected(group);
                  setSearchParams({ group: String(group.id) }, { replace: true });
                }}
              >
                <span>
                  กลุ่มที่ {group.id}
                </span>
                <strong>{group.source_ids.length} Customer ID</strong>
                <small>{group.size} รูปภาพ</small>
              </button>
            ))}
          </aside>
          {displayedSelected && (
            <div className="group-detail" ref={detailRef}>
              <div className="group-title">
                <div>
                  <p className="eyebrow">
                    กลุ่มที่ {displayedSelected.id}
                  </p>
                  <h2>{displayedSelected.source_ids.length} Customer ID · {displayedSelected.size} รูปภาพ</h2>
                  <p className="group-source-summary">
                    <span><b>Technician ID:</b> {displayedSelected.technician_ids.join(", ") || "-"}</span>
                    <span><b>Customer ID:</b> {displayedSelected.source_ids.join(", ")}</span>
                  </p>
                </div>
                <span>
                  <Link2 size={16} />
                  {displayedSelected.subgroups.reduce(
                    (count, subgroup) => count + subgroup.relationships.filter(
                      (relation) => selectedClassifications === null || selectedClassifications.includes(relation.classification),
                    ).length,
                    0,
                  )} คู่ที่ตรงตัวกรอง
                </span>
              </div>
              <GroupContent group={displayedSelected} classifications={selectedClassifications} />
            </div>
          )}
        </div>}
        </>
      )}
    </section>
  );
}
