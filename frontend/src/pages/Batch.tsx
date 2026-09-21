import {
  FolderOpen,
  Images,
  LoaderCircle,
  Play,
  RotateCcw,
  UploadCloud,
} from "lucide-react";
import { CSSProperties, useEffect, useRef, useState } from "react";
import {
  BatchJob,
  ImageGroup,
  createBatch,
  getActiveJob,
  getGroups,
  getJob,
  reanalyzeLibrary,
} from "../api/client";

const stageNames: Record<string, string> = {
  QUEUED: "กำลังวิเคราะห์รูปภาพ",
  EMBEDDING: "กำลังวิเคราะห์รูปภาพ",
  SEARCHING: "กำลังวิเคราะห์รูปภาพ",
  VERIFYING: "กำลังวิเคราะห์รูปภาพ",
  COMPLETED: "เสร็จสิ้น",
  FAILED: "วิเคราะห์ไม่สำเร็จ",
};

export function Batch() {
  const [files, setFiles] = useState<File[]>([]),
    [job, setJob] = useState<BatchJob | null>(null);
  const [groups, setGroups] = useState<ImageGroup[]>([]);
  const [error, setError] = useState(""),
    [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null),
    folderInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    getActiveJob()
      .then((active) => {
        if (active) setJob(active);
      })
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!job || ["COMPLETED", "FAILED"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getJob(job.id);
        setJob(next);
        if (next.status === "COMPLETED") setGroups((await getGroups()).groups);
      } catch (reason) {
        setError(
          reason instanceof Error ? reason.message : "โหลดสถานะไม่สำเร็จ",
        );
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [job]);
  function choose(selected: FileList | null) {
    const chosen = selected ? Array.from(selected) : [];
    const allowed = new Set(["image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp"]);
    const valid = chosen.filter((file) => allowed.has(file.type) && file.size <= 5 * 1024 * 1024);
    const totalSize = valid.reduce((sum, file) => sum + file.size, 0);
    const withinLimits = chosen.length <= 5000 && totalSize <= 1000 * 1024 * 1024;
    setFiles(withinLimits ? valid : []);
    setJob(null);
    setGroups([]);
    setError(
      chosen.length > 5000
        ? "เลือกได้สูงสุดครั้งละ 5,000 ไฟล์"
        : totalSize > 1000 * 1024 * 1024
          ? "ขนาดไฟล์รวมต้องไม่เกิน 1000 MB"
          : valid.length !== chosen.length
            ? "มีไฟล์ที่ไม่รองรับหรือมีขนาดเกิน 5 MB จึงไม่ได้นำมาวิเคราะห์"
            : "",
    );
  }
  async function start() {
    if (!files.length) return;
    setUploading(true);
    setError("");
    try {
      const created = await createBatch(files);
      setJob({
        id: created.job_id,
        status: created.status,
        total: created.file_count,
        processed: 0,
        error: null,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "อัปโหลดไม่สำเร็จ");
    } finally {
      setUploading(false);
    }
  }
  async function reanalyze() {
    setUploading(true);
    setError("");
    setGroups([]);
    try {
      const created = await reanalyzeLibrary();
      setJob({
        id: created.job_id,
        status: created.status,
        total: created.file_count,
        processed: 0,
        error: null,
      });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "เริ่มวิเคราะห์ใหม่ไม่สำเร็จ",
      );
    } finally {
      setUploading(false);
    }
  }
  const progress = job
    ? Math.round((job.processed / Math.max(1, job.total)) * 100)
    : 0;
  return (
    <section>
      <header className="page-head">
        <div>
          <p className="eyebrow">วิเคราะห์แบบกลุ่ม</p>
          <h1>วิเคราะห์หลายภาพ</h1>
          <p>ค้นหาเฉพาะภาพที่มีแนวโน้มเกี่ยวข้องกัน โดยไม่เปรียบเทียบทุกคู่</p>
        </div>
      </header>
      <div className="batch-picker panel">
        <UploadCloud size={38} />
        <h2>
          {files.length
            ? `เลือกแล้ว ${files.length} ภาพ`
            : "เลือกภาพที่ต้องการตรวจ"}
        </h2>
        <p>
          {files.length
            ? `${(files.reduce((sum, file) => sum + file.size, 0) / 1048576).toFixed(1)} MB`
            : "เลือกไฟล์หรือโฟลเดอร์ที่ต้องการตรวจ"}
        </p>
        <div className="picker-actions">
          <button onClick={() => fileInput.current?.click()}>
            <Images size={18} /> อัปโหลดไฟล์
          </button>
          <button onClick={() => folderInput.current?.click()}>
            <FolderOpen size={18} /> อัปโหลดโฟลเดอร์
          </button>
        </div>
        <input
          ref={fileInput}
          hidden
          type="file"
          accept=".jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp"
          multiple
          onChange={(event) => choose(event.target.files)}
        />
        <input
          ref={folderInput}
          hidden
          type="file"
          accept=".jpg,.jpeg,.png,.webp,.tif,.tiff,.bmp"
          multiple
          {...{ webkitdirectory: "", directory: "" }}
          onChange={(event) => choose(event.target.files)}
        />
        <p className="upload-limits">รองรับ JPG, PNG, WebP, TIFF และ BMP · สูงสุด 5,000 ไฟล์ · ไม่เกิน 5 MB ต่อไฟล์ · รวมไม่เกิน 1,000 MB</p>
      </div>
      <div className="batch-run-actions">
        <button
          className="primary"
          disabled={
            !files.length ||
            uploading ||
            (!!job && !["COMPLETED", "FAILED"].includes(job.status))
          }
          onClick={start}
        >
          {uploading ? (
            <LoaderCircle className="spin" size={19} />
          ) : (
            <Play size={19} />
          )}{" "}
          {uploading ? "กำลังเตรียมวิเคราะห์..." : "วิเคราะห์ภาพที่เลือก"}
        </button>
        <button
          className="reanalyze"
          disabled={
            uploading ||
            (!!job && !["COMPLETED", "FAILED"].includes(job.status))
          }
          onClick={reanalyze}
        >
          <RotateCcw size={18} /> วิเคราะห์ข้อมูลเดิมใหม่
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {job && (
        <div className="job-progress panel">
          <div className="job-progress-overview">
            <div>
              <p className="eyebrow">สถานะงาน</p>
              <h2>{stageNames[job.status] ?? job.status}</h2>
              {job.status === "COMPLETED" ? (
                <p className="working-note">สามารถดูรูปภาพที่ใช้ซ้ำได้ที่เมนูกลุ่มภาพที่ใช้ซ้ำ</p>
              ) : job.status === "FAILED" ? (
                <p className="working-note">กรุณาตรวจสอบการเชื่อมต่อแล้วลองอีกครั้ง</p>
              ) : null}
            </div>
            <div className="batch-progress-summary">
              <div
                className="batch-progress-donut"
                role="progressbar"
                aria-label="ความคืบหน้าการวิเคราะห์ภาพ"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progress}
                style={{ "--progress": `${progress}%` } as CSSProperties}
              >
                <div>
                  <strong>{progress}%</strong>
                  <span>ประมวลผลแล้ว</span>
                </div>
              </div>
              <div className="batch-progress-counts">
                <span>
                  ประมวลผลเสร็จแล้ว{" "}
                  <strong>{job.processed.toLocaleString()} ภาพ</strong>
                </span>
                <span>
                  เหลืออีก{" "}
                  <strong>
                    {Math.max(0, job.total - job.processed).toLocaleString()}
                    {" ภาพ"}
                  </strong>
                </span>
                <span>
                  ทั้งหมด <strong>{job.total.toLocaleString()} ภาพ</strong>
                </span>
              </div>
            </div>
          </div>
          <div
            className={`progress-track ${job.status !== "COMPLETED" && job.status !== "FAILED" ? "is-working" : ""}`}
          >
            <span style={{ width: `${progress}%` }} />
          </div>
          <small>{progress}%</small>
          {job.status === "FAILED" && <div className="error">ระบบไม่สามารถวิเคราะห์รูปภาพได้ กรุณาลองใหม่</div>}
        </div>
      )}
      {job?.status === "COMPLETED" && (
        <div className="batch-results">
          <div className="panel">
            <span>ภาพทั้งหมด</span>
            <strong>{job.total}</strong>
          </div>
          <div className="panel">
            <span>กลุ่มภาพที่ใช้ซ้ำ</span>
            <strong>{groups.length}</strong>
          </div>
          <div className="panel">
            <span>ภาพในกลุ่ม</span>
            <strong>
              {groups.reduce((sum, group) => sum + group.size, 0)}
            </strong>
          </div>
        </div>
      )}
    </section>
  );
}
