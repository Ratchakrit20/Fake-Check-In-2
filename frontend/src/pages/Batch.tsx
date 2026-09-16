import {
  FolderOpen,
  Images,
  LoaderCircle,
  Play,
  RotateCcw,
  UploadCloud,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
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
  QUEUED: "กำลังเข้าคิว",
  EMBEDDING: "กำลังสร้าง SSCD fingerprint",
  SEARCHING: "กำลังค้นหาภาพที่คล้าย",
  VERIFYING: "กำลังตรวจ SIFT, RANSAC และอวัยวะ",
  COMPLETED: "วิเคราะห์เสร็จแล้ว",
  FAILED: "การวิเคราะห์ล้มเหลว",
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
    setFiles(
      selected
        ? Array.from(selected).filter((file) => file.type.startsWith("image/"))
        : [],
    );
    setJob(null);
    setGroups([]);
    setError("");
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
            : "เลือกหลายไฟล์หรือเลือกทั้งโฟลเดอร์ได้"}
        </p>
        <div className="picker-actions">
          <button onClick={() => fileInput.current?.click()}>
            <Images size={18} /> เลือกหลายไฟล์
          </button>
          <button onClick={() => folderInput.current?.click()}>
            <FolderOpen size={18} /> เลือกโฟลเดอร์
          </button>
        </div>
        <input
          ref={fileInput}
          hidden
          type="file"
          accept="image/*"
          multiple
          onChange={(event) => choose(event.target.files)}
        />
        <input
          ref={folderInput}
          hidden
          type="file"
          accept="image/*"
          multiple
          {...{ webkitdirectory: "", directory: "" }}
          onChange={(event) => choose(event.target.files)}
        />
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
          {uploading ? "กำลังเตรียมงาน..." : "วิเคราะห์ภาพที่เลือก"}
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
          <div className="job-line">
            <div>
              <p className="eyebrow">สถานะงาน</p>
              <h2>{stageNames[job.status] ?? job.status}</h2>
              <p className="working-note">
                ระบบกำลังทำงานอยู่ แต่ละภาพอาจมี candidate หลายคู่
              </p>
            </div>
            <strong>
              {job.processed} / {job.total}
            </strong>
          </div>
          <div
            className={`progress-track ${job.status !== "COMPLETED" && job.status !== "FAILED" ? "is-working" : ""}`}
          >
            <span style={{ width: `${progress}%` }} />
          </div>
          <small>{progress}%</small>
          {job.error && <div className="error">{job.error}</div>}
        </div>
      )}
      {job?.status === "COMPLETED" && (
        <div className="batch-results">
          <div className="panel">
            <span>ภาพทั้งหมด</span>
            <strong>{job.total}</strong>
          </div>
          <div className="panel">
            <span>กลุ่มที่เกี่ยวข้อง</span>
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
