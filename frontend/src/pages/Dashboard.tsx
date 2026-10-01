import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Download,
  Images,
  Link2,
  Network,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BatchJob,
  DashboardData,
  downloadDashboardReport,
  ExportableBbid,
  exportBbidsPdf,
  getActiveJob,
  getDashboard,
  getExportableBbids,
} from "../api/client";
import { formatDisplayDate } from "../utils/date";

const fallback: DashboardData = {
  total_images: 0,
  related_pairs: 0,
  pending_jobs: 0,
  failed_jobs: 0,
  images_in_system: 0,
  reused_images: 0,
  total_jobs: 0,
  reused_jobs: 0,
  duplicate_jobs: [],
};

function Donut({
  value,
  total,
  label,
}: {
  value: number;
  total: number;
  label: string;
}) {
  const percent =
    total > 0 ? Math.min(100, Math.round((value / total) * 100)) : 0;
  return (
    <div className="dashboard-donut-wrap">
      <div
        className="dashboard-donut"
        style={{ "--percent": `${percent}%` } as React.CSSProperties}
      >
        <div>
          <strong>{percent}%</strong>
          <span>{label}</span>
        </div>
      </div>
      <small>
        {value.toLocaleString()} จาก {total.toLocaleString()}
      </small>
    </div>
  );
}

export function Dashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState(fallback);
  const [activeJob, setActiveJob] = useState<BatchJob | null>(null);
  const [exportItems, setExportItems] = useState<ExportableBbid[]>([]);
  const [selectedBbids, setSelectedBbids] = useState<string[]>([]);
  const [exportSearch, setExportSearch] = useState("");
  const [exporting, setExporting] = useState(false);
  const [dateFrom, setDateFrom] = useState("2026-01-01");
  const [dateTo, setDateTo] = useState("2026-12-31");
  const [totalImages, setTotalImages] = useState(() =>
    Number(localStorage.getItem("report-total-images") || 0),
  );
  useEffect(() => {
    let active = true;
    const load = () => {
      void getDashboard()
        .then((result) => {
          if (!active) return;
          setData(result);
          setTotalImages((current) => current || result.images_in_system);
        })
        .catch(() => undefined);
      void getActiveJob()
        .then((result) => {
          if (active) setActiveJob(result);
        })
        .catch(() => undefined);
    };
    void load();
    const timer = window.setInterval(load, 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    const from = dateFrom.replaceAll("-", ""),
      to = dateTo.replaceAll("-", "");
    void getExportableBbids(from, to, exportSearch)
      .then((response) => {
        setExportItems(response.items);
        setSelectedBbids((selected) =>
          selected.filter((bbid) =>
            response.items.some((item) => item.bbid === bbid),
          ),
        );
      })
      .catch(() => setExportItems([]));
  }, [dateFrom, dateTo, exportSearch]);
  useEffect(() => {
    localStorage.setItem("report-total-images", String(totalImages));
  }, [totalImages]);
  const safeTotal = Math.max(totalImages, data.images_in_system);
  const visibleBbids = exportItems.map((item) => item.bbid);
  const areAllVisibleSelected =
    visibleBbids.length > 0 && visibleBbids.every((bbid) => selectedBbids.includes(bbid));

  function toggleAllVisible() {
    setSelectedBbids((selected) =>
      areAllVisibleSelected
        ? selected.filter((bbid) => !visibleBbids.includes(bbid))
        : [...new Set([...selected, ...visibleBbids])],
    );
  }
  const cards = useMemo(
    () =>
      [
        ["ภาพในระบบ", data.images_in_system, Images, "blue"],
        ["ภาพที่ใช้ซ้ำ", data.reused_images, Link2, "violet"],
        ["BBIDทั้งหมด", data.total_jobs, Network, "teal"],
        ["BBIDที่ใช้ภาพซ้ำ", data.reused_jobs, AlertTriangle, "amber"],
        ["รายการที่กำลังวิเคราะห์", data.pending_jobs, Clock3, "amber"],
        [
          "วิเคราะห์แล้ว",
          Math.max(0, data.total_images - data.pending_jobs),
          CheckCircle2,
          "green",
        ],
      ] as const,
    [data],
  );
  return (
    <section>
      <header className="page-head">
        <div>
          <p className="eyebrow">ศูนย์ตรวจสอบหลักฐานภาพ</p>
          <h1>ภาพรวมการวิเคราะห์ภาพซ้ำ</h1>
          {/* <p>ข้อมูลจะอัปเดตจากผลประมวลผลล่าสุดอัตโนมัติทุก 10 วินาที</p> */}
        </div>
      </header>
      <div className="metric-grid">
        {cards.map(([label, value, Icon, color]) => (
          <article className="metric" key={label}>
            <div className={`metric-icon ${color}`}>
              <Icon size={21} />
            </div>
            <span>{label}</span>
            <strong>{value.toLocaleString()}</strong>
          </article>
        ))}
      </div>
      <div className="dashboard-report-grid">
        <section className="panel dashboard-chart-panel">
          <div className="panel-head">
            <div>
              <h2>ภาพในระบบและการใช้ซ้ำ</h2>
              <p>เปรียบเทียบภาพทั้งหมดกับภาพที่พบว่าใช้ซ้ำ</p>
            </div>
          </div>
          <label className="manual-total">
            <span>ภาพทั้งหมด</span>
            <input
              type="number"
              min={data.images_in_system}
              value={totalImages}
              onChange={(event) =>
                setTotalImages(Number(event.target.value) || 0)
              }
            />
          </label>
          <div
            className={`dashboard-image-donuts ${activeJob ? "has-active-job" : ""}`}
          >
            <div>
              <Donut
                value={data.reused_images}
                total={safeTotal}
                label="ภาพใช้ซ้ำ"
              />
              <div className="dashboard-legend">
                <span>
                  ในระบบ <b>{data.images_in_system.toLocaleString()}</b>
                </span>
                <span>
                  ใช้ซ้ำ <b>{data.reused_images.toLocaleString()}</b>
                </span>
              </div>
            </div>
            {activeJob && (
              <div className="dashboard-active-analysis">
                <h3>กำลังตรวจสอบภาพ</h3>
                <Donut
                  value={activeJob.processed}
                  total={activeJob.total}
                  label="ตรวจแล้ว"
                />
                <div className="dashboard-legend">
                  <span>
                    ประมวลผลเสร็จแล้ว{" "}
                    <b>{activeJob.processed.toLocaleString()} ภาพ</b>
                  </span>
                  <span>
                    เหลืออีก{" "}
                    <b>
                      {Math.max(
                        0,
                        activeJob.total - activeJob.processed,
                      ).toLocaleString()}
                      {" ภาพ"}
                    </b>
                  </span>
                </div>
              </div>
            )}
          </div>
        </section>
        <section className="panel dashboard-chart-panel">
          <div className="panel-head">
            <div>
              <h2>BBID ที่พบการใช้ภาพซ้ำ</h2>
              <p>เปรียบเทียบ BBID ทั้งหมดกับ BBID ที่มีภาพใช้ซ้ำ</p>
            </div>
          </div>
          <Donut
            value={data.reused_jobs}
            total={data.total_jobs}
            label="BBID ที่ใช้ภาพซ้ำ"
          />
          <div className="dashboard-legend">
            <span>
              BBID ทั้งหมด <b>{data.total_jobs.toLocaleString()}</b>
            </span>
            <span>
              พบใช้ซ้ำ <b>{data.reused_jobs.toLocaleString()}</b> BBID
            </span>
          </div>
          <button
            className="report-download"
            onClick={() => downloadDashboardReport(safeTotal)}
          >
            <Download size={17} /> ดาวน์โหลดเอกสาร
          </button>
        </section>
      </div>
      <section className="panel duplicate-job-panel">
        <div className="panel-head">
          <div>
            <h2>เลข BBID ที่พบการใช้ภาพซ้ำ</h2>
            <p>ใช้สำหรับตรวจสอบต่อและนำไปทำรายงาน</p>
          </div>
          <strong>{data.duplicate_jobs.length.toLocaleString()} BBID</strong>
        </div>
        {data.duplicate_jobs.length ? (
          <div className="duplicate-job-table">
            <div className="table-head">
              <span>BBID</span>
              <span>ภาพในระบบ</span>
              <span>ภาพใช้ซ้ำ</span>
              <span>ภาพที่เชื่อมโยง</span>
            </div>
            {data.duplicate_jobs.map((job) => (
              <button
                type="button"
                className="duplicate-job-row"
                key={job.job_number}
                onClick={() =>
                  navigate(`/groups?bbid=${encodeURIComponent(job.job_number)}`)
                }
                aria-label={`เปิดกลุ่มภาพของ BBID ${job.job_number}`}
              >
                <strong>{job.job_number}</strong>
                <span>{job.images_in_system}</span>
                <span>{job.reused_images}</span>
                <span>{job.evidence_links}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="dashboard-empty">ยังไม่พบเลขงานที่ใช้ภาพซ้ำ</div>
        )}
      </section>
      <section className="panel duplicate-job-panel export-panel">
        <div className="panel-head">
          <div>
            <h2>Export รายงาน PDF</h2>
            <p>เลือก BBID และช่วงวันที่ก่อนสร้างรายงานรวม</p>
          </div>
          <button
            className="report-download"
            disabled={!selectedBbids.length || exporting}
            onClick={() => {
              setExporting(true);
              void exportBbidsPdf(
                selectedBbids,
                dateFrom.replaceAll("-", ""),
                dateTo.replaceAll("-", ""),
              ).finally(() => setExporting(false));
            }}
          >
            {exporting
              ? "กำลังสร้าง PDF..."
              : `Export PDF (${selectedBbids.length})`}
          </button>
        </div>
        <div className="export-controls">
          <div className="export-filters">
            <label>
              <span>ตั้งแต่วันที่</span>
              <input
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
              />
            </label>
            <span className="export-date-separator">ถึง</span>
            <label>
              <span>ถึงวันที่</span>
              <input
                type="date"
                value={dateTo}
                onChange={(event) => setDateTo(event.target.value)}
              />
            </label>
            <label className="export-search">
              <span>ค้นหา BBID</span>
              <input
                placeholder="ระบุเลข BBID"
                value={exportSearch}
                onChange={(event) => setExportSearch(event.target.value)}
              />
            </label>
          </div>
          <div className="export-selection-actions">
            <span>เลือกแล้ว {selectedBbids.length} รายการ</span>
            <button type="button" onClick={toggleAllVisible} disabled={!visibleBbids.length}>
              {areAllVisibleSelected ? "ยกเลิกเลือกทั้งหมด" : "เลือกทั้งหมด"}
            </button>
            <button type="button" onClick={() => setSelectedBbids([])} disabled={!selectedBbids.length}>
              ล้างที่เลือก
            </button>
          </div>
        </div>
        <div className="duplicate-job-table export-table">
          <div className="table-head">
            <span>เลือก</span>
            <span>BBID</span>
            <span>วันที่</span>
            <span>สถานะ</span>
          </div>
          {exportItems.map((item) => (
            <label className="duplicate-job-row" key={item.bbid}>
              <input
                type="checkbox"
                checked={selectedBbids.includes(item.bbid)}
                onChange={(event) =>
                  setSelectedBbids((selected) =>
                    event.target.checked
                      ? [...selected, item.bbid]
                      : selected.filter((bbid) => bbid !== item.bbid),
                  )
                }
              />
              <strong>{item.bbid}</strong>
              <span>{item.dates.map(formatDisplayDate).filter(Boolean).join(", ")}</span>
              <span className={`export-status ${item.exported ? "is-exported" : "is-pending"}`}>
                {item.exported ? "Export แล้ว (เลือกซ้ำได้)" : "ยังไม่ Export"}
              </span>
            </label>
          ))}
        </div>
      </section>
      {/* <div className="panel">
        <div className="panel-head">
          <div>
            <h2>ลำดับการตรวจสอบ</h2>
            <p>
              ระบบคัดกรองภาพอย่างรวดเร็วก่อน
              แล้วตรวจเฉพาะคู่ที่น่าสงสัยอย่างละเอียด
            </p>
          </div>
        </div>
        <div className="pipeline">
          {[
            "ตรวจไฟล์ที่เหมือนกัน",
            "จดจำลักษณะสำคัญของภาพ",
            "ค้นหาคู่ภาพที่น่าสงสัย",
            "ตรวจรายละเอียดและตำแหน่งที่ตรงกัน",
            "สรุปผลการใช้ภาพซ้ำ",
          ].map((item, i) => (
            <div key={item}>
              <span>{String(i + 1).padStart(2, "0")}</span>
              <strong>{item}</strong>
            </div>
          ))}
        </div>
      </div> */}
    </section>
  );
}
