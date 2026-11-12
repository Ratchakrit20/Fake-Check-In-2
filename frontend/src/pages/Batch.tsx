import {
  FolderOpen,
  Images,
  LoaderCircle,
  Square,
  Play,
  RotateCcw,
  UploadCloud,
} from "lucide-react";
import { CSSProperties, useEffect, useRef, useState } from "react";
import {
  BatchJob,
  ImageGroup,
  createBatch,
  cancelJob,
  getActiveJob,
  getLmrImportDates,
  getGroups,
  getJob,
  getJobProgress,
  importLmrDate,
  LmrImportDate,
  reanalyzeLibrary,
  resumeJob,
} from "../api/client";

const stageNames: Record<string, string> = {
  QUEUED: "กำลังวิเคราะห์รูปภาพ",
  VALIDATING: "กำลังตรวจคุณภาพภาพ",
  EMBEDDING: "กำลังเตรียมภาพสำหรับวิเคราะห์",
  SEARCHING: "กำลังค้นหาภาพที่อาจเกี่ยวข้อง",
  VERIFYING: "กำลังตรวจสอบคู่ภาพ",
  COMPLETED: "เสร็จสิ้น",
  CANCELLED: "หยุดการวิเคราะห์แล้ว",
  INTERRUPTED: "การวิเคราะห์ถูกขัดจังหวะ",
  FAILED: "วิเคราะห์ไม่สำเร็จ",
};

const lmrRootCategory = "__date_root__";

function lmrCategoryLabel(category: string): string {
  return category === lmrRootCategory ? "ไฟล์ในโฟลเดอร์วันที่โดยตรง" : category;
}

export function Batch() {
  const [files, setFiles] = useState<File[]>([]),
    [job, setJob] = useState<BatchJob | null>(null);
  const jobRef = useRef<BatchJob | null>(null);
  const progressFloor = useRef<{ jobId: string; value: number } | null>(null);
  const [groups, setGroups] = useState<ImageGroup[]>([]);
  const [error, setError] = useState(""),
    [uploading, setUploading] = useState(false);
  const [qualityNotice, setQualityNotice] = useState("");
  const [lmrDates, setLmrDates] = useState<LmrImportDate[]>([]);
  const [lmrAvailable, setLmrAvailable] = useState<boolean | null>(null);
  const [selectedLmrDate, setSelectedLmrDate] = useState("");
  const [selectedLmrCategories, setSelectedLmrCategories] = useState<string[] | null>(null);
  const [lmrError, setLmrError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null),
    folderInput = useRef<HTMLInputElement>(null);

  function replaceJob(next: BatchJob | null) {
    if (!next) {
      jobRef.current = null;
      progressFloor.current = null;
      setJob(null);
      return;
    }

    const current = jobRef.current;
    const merged = current?.id === next.id
      ? { ...next, processed: Math.max(current.processed, next.processed) }
      : next;
    let previousFloor = progressFloor.current?.jobId === merged.id
      ? progressFloor.current.value
      : 0;
    if (!previousFloor) {
      try {
        const saved = JSON.parse(sessionStorage.getItem("batch-progress-floor") ?? "null") as
          | { jobId?: string; value?: number }
          | null;
        if (saved?.jobId === merged.id && Number.isFinite(saved.value)) {
          previousFloor = Math.max(0, saved.value ?? 0);
        }
      } catch {
        // Progress remains protected for this page session if storage is unavailable.
      }
    }
    const value = Math.max(previousFloor, getJobProgress(merged));
    progressFloor.current = { jobId: merged.id, value };
    jobRef.current = merged;
    try {
      sessionStorage.setItem("batch-progress-floor", JSON.stringify({ jobId: merged.id, value }));
    } catch {
      // The in-memory floor still prevents polling responses from moving backward.
    }
    setJob(merged);
  }

  useEffect(() => {
    getActiveJob()
      .then((active) => {
        if (active) replaceJob(active);
      })
      .catch((reason) => {
        setError(reason instanceof Error ? `เชื่อมต่อ API ไม่ได้: ${reason.message}` : "เชื่อมต่อ API ไม่ได้");
      });
  }, []);
  useEffect(() => {
    getLmrImportDates()
      .then((result) => {
        setLmrAvailable(result.available);
        setLmrDates(result.dates);
        setSelectedLmrDate((current) => current || result.dates[0]?.date || "");
      })
      .catch((reason) => {
        setLmrAvailable(false);
        setLmrError(reason instanceof Error ? reason.message : "โหลดคลัง LMR ไม่สำเร็จ");
      });
  }, []);
  useEffect(() => {
    if (!job || ["COMPLETED", "CANCELLED", "INTERRUPTED", "FAILED"].includes(job.status)) return;
    const jobId = job.id;
    let cancelled = false;
    let timer = 0;
    const poll = async () => {
      try {
        const next = await getJob(jobId);
        if (cancelled) return;
        replaceJob(next);
        if (["COMPLETED", "CANCELLED", "INTERRUPTED", "FAILED"].includes(next.status)) {
          if (next.status === "COMPLETED") setGroups((await getGroups()).groups);
          const lmrStatus = await getLmrImportDates();
          setLmrAvailable(lmrStatus.available);
          setLmrDates(lmrStatus.dates);
        }
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : "โหลดสถานะไม่สำเร็จ");
        }
      }
      if (!cancelled) timer = window.setTimeout(poll, 2000);
    };
    timer = window.setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [job?.id, job?.status]);
  function choose(selected: FileList | null) {
    const chosen = selected ? Array.from(selected) : [];
    const allowed = new Set(["image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp"]);
    const valid = chosen.filter((file) => allowed.has(file.type) && file.size <= 5 * 1024 * 1024);
    const totalSize = valid.reduce((sum, file) => sum + file.size, 0);
    const withinLimits = chosen.length <= 5000 && totalSize <= 1000 * 1024 * 1024;
    setFiles(withinLimits ? valid : []);
    replaceJob(null);
    setGroups([]);
    setQualityNotice("");
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
      setQualityNotice(
        created.unverifiable_count
          ? `มี ${created.unverifiable_count.toLocaleString()} ภาพที่มืดเกินเกณฑ์ ระบบจะบันทึกเป็น “ตรวจสอบองค์ประกอบไม่ได้” และไม่นำไปจับคู่`
          : "",
      );
      replaceJob({
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
  async function importLmr() {
    if (!selectedLmrDate) return;
    setUploading(true);
    setError("");
    setLmrError("");
    setQualityNotice("");
    setGroups([]);
    try {
      const result = await importLmrDate(selectedLmrDate, selectedLmrCategories ?? []);
      if (!result.job_id) {
        replaceJob(null);
        setQualityNotice(
          `พบ ${result.found_count.toLocaleString()} ภาพ · วิเคราะห์แล้ว ${result.already_analyzed_count.toLocaleString()} ภาพ · ไม่มีภาพที่ต้องส่งวิเคราะห์ใหม่${result.invalid_count ? ` · ข้ามไฟล์ที่เปลี่ยนหรือลบระหว่างสแกน ${result.invalid_count.toLocaleString()} ไฟล์` : ""}`,
        );
        const refreshed = await getLmrImportDates();
        setLmrDates(refreshed.dates);
        return;
      }
      setQualityNotice(
        `เพิ่มภาพใหม่ ${result.imported_count.toLocaleString()} ภาพ${result.pending_retry_count ? ` · ส่งภาพที่ค้างวิเคราะห์เดิม ${result.pending_retry_count.toLocaleString()} ภาพเข้าคิวอีกครั้ง` : ""} · ภาพที่วิเคราะห์เสร็จแล้วและข้าม ${result.already_analyzed_count.toLocaleString()} ภาพ · รวมส่งวิเคราะห์ ${result.scheduled_count.toLocaleString()} ภาพ โดยไม่คัดลอกไฟล์`,
      );
      replaceJob({
        id: result.job_id,
        status: result.status,
        total: result.scheduled_count,
        processed: 0,
        error: null,
      });
    } catch (reason) {
      setLmrError(reason instanceof Error ? reason.message : "นำเข้าคลัง LMR ไม่สำเร็จ");
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
      replaceJob({
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
  async function cancel() {
    if (!job) return;
    setUploading(true);
    setError("");
    try {
      replaceJob(await cancelJob(job.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "หยุดการวิเคราะห์ไม่สำเร็จ");
    } finally {
      setUploading(false);
    }
  }
  async function resume() {
    if (!job) return;
    setUploading(true);
    setError("");
    try {
      replaceJob(await resumeJob(job.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "ทำต่อจากจุดเดิมไม่สำเร็จ");
    } finally {
      setUploading(false);
    }
  }
  const progress = job
    ? Math.max(
        getJobProgress(job),
        progressFloor.current?.jobId === job.id ? progressFloor.current.value : 0,
      )
    : 0;
  const isRunning = !!job && !["COMPLETED", "CANCELLED", "INTERRUPTED", "FAILED"].includes(job.status);
  const selectedLmrEntry = lmrDates.find((item) => item.date === selectedLmrDate);
  const availableLmrCategories = selectedLmrDate === "all"
    ? [...new Set(lmrDates.flatMap((item) => item.categories))].sort((a, b) => {
        if (a === lmrRootCategory) return -1;
        if (b === lmrRootCategory) return 1;
        return a.localeCompare(b, "th");
      })
    : selectedLmrEntry?.categories ?? [];
  const allLmrCategoriesSelected = selectedLmrCategories === null;
  const lmrTotals = lmrDates.reduce(
    (totals, item) => ({
      images: totals.images + item.image_count,
      analyzed: totals.analyzed + item.analyzed_count,
      pending: totals.pending + item.pending_count,
      notImported: totals.notImported + item.not_imported_count,
    }),
    { images: 0, analyzed: 0, pending: 0, notImported: 0 },
  );
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
          <button disabled={isRunning} onClick={() => fileInput.current?.click()}>
            <Images size={18} /> อัปโหลดไฟล์
          </button>
          <button disabled={isRunning} onClick={() => folderInput.current?.click()}>
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
      <div className="lmr-import panel">
        <div className="lmr-import-heading">
          <p className="eyebrow">คลังภาพบนเครื่องเซิร์ฟเวอร์</p>
          <h2>นำเข้าจากคลัง LMR โดยไม่คัดลอกไฟล์</h2>
          <p>เลือกวันและหมวดหมู่ที่ต้องการ ระบบจะอ่านไฟล์เดิมจากคลังและบันทึกสถานะการวิเคราะห์ไว้ในฐานข้อมูล</p>
          {lmrAvailable === false && (
            <p className="lmr-unavailable">{lmrError || "backend ยังเข้าไม่ถึงคลัง LMR ตรวจค่า lmr_import.root ใน config/default.yaml"}</p>
          )}
        </div>
        <div className="lmr-import-form">
          <label className="lmr-field">
            <span>1. เลือกวันที่</span>
            <select
              aria-label="เลือกวันที่จากคลัง LMR"
              value={selectedLmrDate}
              onChange={(event) => {
                setSelectedLmrDate(event.target.value);
                setSelectedLmrCategories(null);
              }}
              disabled={!lmrAvailable || uploading || isRunning || lmrDates.length === 0}
            >
              <option value="">
                {lmrAvailable === null
                  ? "กำลังโหลดวันที่..."
                  : !lmrAvailable
                    ? "คลัง LMR ยังไม่พร้อม"
                    : lmrDates.length === 0
                      ? "ไม่พบโฟลเดอร์วันที่"
                      : "เลือกวันที่ที่ต้องการ"}
              </option>
              <option value="all">
                ทุกวัน · วิเคราะห์แล้ว {lmrTotals.analyzed.toLocaleString()}/{lmrTotals.images.toLocaleString()} ภาพ · ค้าง {lmrTotals.pending.toLocaleString()} · ยังไม่นำเข้า {lmrTotals.notImported.toLocaleString()}
              </option>
              {lmrDates.map((item) => (
                <option key={item.date} value={item.date}>
                  {item.date} · วิเคราะห์แล้ว {item.analyzed_count.toLocaleString()}/{item.image_count.toLocaleString()} · ค้าง {item.pending_count.toLocaleString()} · ยังไม่นำเข้า {item.not_imported_count.toLocaleString()}
                </option>
              ))}
            </select>
            <small>เลือกวันเดียว หรือเลือกทุกวันในคลัง</small>
          </label>
          <fieldset className="lmr-category-picker" disabled={!selectedLmrDate || uploading || isRunning}>
            <legend>2. เลือกหมวดหมู่</legend>
            {!selectedLmrDate ? (
              <p className="lmr-category-empty">เลือกวันที่ก่อน เพื่อดูหมวดหมู่ที่มีภาพ</p>
            ) : availableLmrCategories.length === 0 ? (
              <p className="lmr-category-empty">ไม่พบหมวดหมู่ที่มีภาพในวันที่เลือก</p>
            ) : (
              <div className="lmr-category-options">
                <label className="lmr-category-option lmr-category-all">
                  <input
                    type="checkbox"
                    checked={allLmrCategoriesSelected}
                    onChange={() => setSelectedLmrCategories(null)}
                  />
                  <span>ทุกหมวด</span>
                </label>
                {availableLmrCategories.map((category) => {
                  const checked = allLmrCategoriesSelected || (selectedLmrCategories ?? []).includes(category);
                  return (
                    <label className="lmr-category-option" key={category}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => {
                          const next = allLmrCategoriesSelected
                            ? availableLmrCategories.filter((item) => item !== category)
                            : (selectedLmrCategories ?? []).includes(category)
                              ? (selectedLmrCategories ?? []).filter((item) => item !== category)
                              : [...(selectedLmrCategories ?? []), category];
                          setSelectedLmrCategories(
                            next.length === availableLmrCategories.length && next.length > 0 ? null : next,
                          );
                        }}
                      />
                      <span>{lmrCategoryLabel(category)}</span>
                    </label>
                  );
                })}
              </div>
            )}
            <small>
              {selectedLmrDate === "all"
                ? `มี ${availableLmrCategories.length} หมวดจากทุกวัน`
                : selectedLmrEntry
                  ? `มี ${availableLmrCategories.length} หมวด · ${selectedLmrEntry.image_count.toLocaleString()} ภาพ`
                  : "เลือกได้มากกว่าหนึ่งหมวด"}
            </small>
          </fieldset>
          <div className="lmr-import-action">
            <p>ระบบจะข้ามภาพที่วิเคราะห์เสร็จแล้ว และทำต่อเฉพาะภาพใหม่หรือภาพที่ยังค้าง</p>
            <button
              className="primary"
              disabled={!selectedLmrDate || availableLmrCategories.length === 0 || selectedLmrCategories?.length === 0 || uploading || isRunning}
              onClick={importLmr}
            >
              {uploading ? <LoaderCircle className="spin" size={18} /> : <FolderOpen size={18} />}
              เริ่มนำเข้าตามที่เลือก
            </button>
          </div>
        </div>
        {lmrError && lmrAvailable !== false && <p className="lmr-error">{lmrError}</p>}
      </div>
      <div className="batch-run-actions">
        <button
          className="primary"
          disabled={
            !files.length ||
            uploading ||
            isRunning
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
            isRunning
          }
          onClick={reanalyze}
        >
          <RotateCcw size={18} /> วิเคราะห์ข้อมูลเดิมใหม่
        </button>
        {isRunning && (
          <button className="reanalyze cancel-analysis" disabled={uploading} onClick={cancel}>
            <Square size={16} fill="currentColor" /> หยุดการวิเคราะห์
          </button>
        )}
      </div>
      {error && <div className="error">{error}</div>}
      {qualityNotice && <div className="working-note">{qualityNotice}</div>}
      {job && ["FAILED", "INTERRUPTED", "CANCELLED"].includes(job.status) && job.processed < job.total && (
        <button className="reanalyze" disabled={uploading} onClick={resume}>
          <RotateCcw size={18} /> ทำต่อจากจุดเดิม ({job.processed.toLocaleString()}/{job.total.toLocaleString()})
        </button>
      )}
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
              ) : job.status === "CANCELLED" ? (
                <p className="working-note">หยุดงานแล้ว สามารถทำต่อจากจุดเดิมได้ โดยระบบจะข้ามภาพที่เสร็จแล้ว</p>
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
                  <span>ความคืบหน้าโดยรวม</span>
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
            className={`progress-track ${!["COMPLETED", "CANCELLED", "FAILED"].includes(job.status) ? "is-working" : ""}`}
          >
            <span style={{ width: `${progress}%` }} />
          </div>
          <small>{progress}%</small>
          {job.status === "FAILED" && <div className="error">ระบบไม่สามารถวิเคราะห์รูปภาพได้ กรุณาลองใหม่</div>}
          {job.status === "CANCELLED" && <div className="working-note">ผลที่วิเคราะห์เสร็จก่อนกดหยุดจะถูกเก็บไว้ แต่รายการที่เหลือจะไม่ถูกประมวลผลต่อ</div>}
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
