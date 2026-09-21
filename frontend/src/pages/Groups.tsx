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

const classificationNames: Record<string, string> = {
  exact_file: "ไฟล์เดียวกัน 100%",
  same_image: "ภาพเดียวกันแต่ไฟล์ต่างกัน",
  edited_or_cropped: "ภาพเดิมถูกดัดแปลง",
  background_replaced: "สงสัยเปลี่ยนฉาก",
  same_scene_new_capture: "พบฉากหลังสอดคล้องกัน",
  repeated_checkin: "พบคนและฉากเชื่อมโยงกัน",
};

function GroupContent({ group }: { group: ImageGroup }) {
  const navigate = useNavigate();
  const images = Array.from(
    new Map(group.subgroups.flatMap((item) => item.images).map((image) => [image.id, image])).values(),
  );
  const relationships = group.subgroups.flatMap((item: RelationshipSubgroup) => item.relationships);
  return (
    <section className="relationship-subgroup">
      <div className="group-gallery">
        {images.map((image) => (
          <figure key={image.id}>
            <img src={image.url} alt={image.filename} loading="lazy" />
            <figcaption>
              <strong title={image.filename}>{image.filename}</strong>
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
                <strong className="relation-name-first" title={first?.filename}>
                  {first?.filename}
                </strong>
                <small>เชื่อมโยงกับ</small>
                <strong
                  className="relation-name-second"
                  title={second?.filename}
                >
                  {second?.filename}
                </strong>
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
  const detailRef = useRef<HTMLDivElement>(null);
  const [detailHeight, setDetailHeight] = useState(0);
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
  }, [selected]);
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
        <div className="groups-layout">
          <aside
            className="group-list panel"
            style={
              {
                "--detail-height": `${detailHeight || window.innerHeight}px`,
              } as CSSProperties
            }
          >
            {groups.map((group) => (
              <button
                className={selected?.id === group.id ? "active" : ""}
                key={group.id}
                onClick={() => {
                  setSelected(group);
                  setSearchParams({ group: String(group.id) }, { replace: true });
                }}
              >
                <span>
                  กลุ่มที่ {group.id}
                </span>
                <strong>{group.source_ids.length} BBID</strong>
                <small>{group.size} รูปภาพ</small>
              </button>
            ))}
          </aside>
          {selected && (
            <div className="group-detail" ref={detailRef}>
              <div className="group-title">
                <div>
                  <p className="eyebrow">
                    กลุ่มที่ {selected.id}
                  </p>
                  <h2>{selected.source_ids.length} BBID · {selected.size} รูปภาพ</h2>
                </div>
                <span>
                  <Link2 size={16} />
                  {selected.relationship_count} คู่
                </span>
              </div>
              <GroupContent group={selected} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}
