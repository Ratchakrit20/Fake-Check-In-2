import {
  CalendarDays,
  FileDown,
  Images,
  Network,
  RefreshCw,
  UsersRound,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  BatchJob,
  DashboardData,
  exportDateRangePdf,
  getActiveJob,
  getDashboard,
  getJobProgress,
} from "../api/client";
import { DonutChart } from "../components/dashboard/DonutChart";
import { TechnicianBarChart } from "../components/dashboard/TechnicianBarChart";
import { VerticalTrendChart } from "../components/dashboard/VerticalTrendChart";
import { formatDisplayDate } from "../utils/date";

const emptyData: DashboardData = {
  total_images: 0,
  related_pairs: 0,
  pending_jobs: 0,
  failed_jobs: 0,
  images_in_system: 0,
  reused_images: 0,
  total_jobs: 0,
  reused_jobs: 0,
  duplicate_jobs: [],
  insights: {
    daily: [],
    technicians: [],
    export_preview: {
      group_count: 0,
      selected_images: 0,
      report_images: 0,
      cross_date_images: 0,
      customer_ids: 0,
      technician_ids: 0,
      cross_dates: [],
    },
  },
};

function toApiDate(value: string) {
  return value.replaceAll("-", "");
}

export function InsightsDashboard() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [exportDate, setExportDate] = useState("");
  const [exportPreview, setExportPreview] = useState<
    DashboardData["insights"]["export_preview"] | null
  >(null);
  const [exportError, setExportError] = useState("");
  const [data, setData] = useState(emptyData);
  const [activeJob, setActiveJob] = useState<BatchJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const [dashboard, job] = await Promise.all([
          getDashboard(
            dateFrom ? toApiDate(dateFrom) : undefined,
            dateTo ? toApiDate(dateTo) : undefined,
          ),
          getActiveJob(),
        ]);
        if (mounted) {
          setData(dashboard);
          setActiveJob(job);
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 15_000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [dateFrom, dateTo]);

  useEffect(() => {
    let current = true;
    setExportPreview(null);
    setExportError("");
    if (exportDate) {
      const date = toApiDate(exportDate);
      void getDashboard(date, date)
        .then((result) => {
          if (current) setExportPreview(result.insights.export_preview);
        })
        .catch(() => {
          if (current) setExportError("โหลดข้อมูลสรุปสำหรับ Export ไม่สำเร็จ");
        });
    }
    return () => {
      current = false;
    };
  }, [exportDate]);

  const imageTrend = useMemo(
    () =>
      data.insights.daily.map((point) => ({
        date: point.date,
        primary: point.total_images,
        secondary: point.reused_images,
      })),
    [data],
  );
  const customerTrend = useMemo(
    () =>
      data.insights.daily.map((point) => ({
        date: point.date,
        primary: point.total_customer_ids,
        secondary: point.reused_customer_ids,
      })),
    [data],
  );
  const preview = exportPreview;
  const canExport = Boolean(exportDate && preview?.group_count && !exporting);

  return (
    <section className="insights-dashboard">
      <header className="page-head insights-head">
        <div>
          <p className="eyebrow">DASHBOARD</p>
          <h1>ภาพรวมผลตรวจในระบบ</h1>
          <p>
            ติดตามปริมาณภาพ, Customer ID การใช้ภาพซ้ำในช่วงวันที่เลือก
          </p>
        </div>
        <button
          className="insight-refresh"
          type="button"
          onClick={() => {
            setLoading(true);
            void getDashboard(
              dateFrom ? toApiDate(dateFrom) : undefined,
              dateTo ? toApiDate(dateTo) : undefined,
            )
              .then(setData)
              .finally(() => setLoading(false));
          }}
        >
          <RefreshCw size={16} className={loading ? "spin" : ""} /> อัปเดตข้อมูล
        </button>
      </header>

      <section className="panel insight-filter-panel">
        <div className="insight-filter-title">
          <CalendarDays size={19} />
          <div>
            <strong>ช่วงข้อมูล</strong>
            <span>เลือกวันที่เพื่อดูกราฟ</span>
          </div>
        </div>
        <label>
          ตั้งแต่
          <input
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
          />
        </label>
        <label>
          ถึง
          <input
            type="date"
            value={dateTo}
            min={dateFrom}
            onChange={(event) => setDateTo(event.target.value)}
          />
        </label>
        <button
          type="button"
          onClick={() => {
            setDateFrom("");
            setDateTo("");
          }}
        >
          ดูทั้งหมด
        </button>
      </section>

      {activeJob && (
        <section className="panel active-job-panel">
          <div>
            <p className="eyebrow">กำลังประมวลผล</p>
            <h2>ระบบกำลังวิเคราะห์ภาพ</h2>
            <p>
              {activeJob.processed.toLocaleString()} จาก{" "}
              {activeJob.total.toLocaleString()} ภาพ · สถานะ {activeJob.status}
            </p>
          </div>
          <DonutChart
            value={getJobProgress(activeJob)}
            total={100}
            label="ความคืบหน้า"
          />
        </section>
      )}

      <div className="insight-donut-grid">
        <section className="panel insight-donut-panel">
          <div>
            <h2>สัดส่วนภาพ</h2>
            <p>ภาพทั้งหมดเทียบกับภาพที่พบการใช้ซ้ำ</p>
          </div>
          <DonutChart
            value={data.reused_images}
            total={data.images_in_system}
            label="ภาพใช้ซ้ำ"
          />
          <div className="insight-totals">
            <span>
              <Images size={15} />
              ทั้งหมด <b>{data.images_in_system.toLocaleString()}</b>
            </span>
            <span>
              ใช้ซ้ำ <b>{data.reused_images.toLocaleString()}</b>
            </span>
          </div>
        </section>
        <section className="panel insight-donut-panel">
          <div>
            <h2>สัดส่วน Customer ID</h2>
            <p>Customer ID ทั้งหมดเทียบกับ Customer ID ที่พบภาพใช้ซ้ำ</p>
          </div>
          <DonutChart
            value={data.reused_jobs}
            total={data.total_jobs}
            label="Customer ID ซ้ำ"
          />
          <div className="insight-totals">
            <span>
              <UsersRound size={15} />
              ทั้งหมด <b>{data.total_jobs.toLocaleString()}</b>
            </span>
            <span>
              ใช้ซ้ำ <b>{data.reused_jobs.toLocaleString()}</b>
            </span>
          </div>
        </section>
      </div>

      <div className="insight-chart-grid">
        <section className="panel insight-chart-panel">
          <div className="panel-head">
            <div>
              <h2>จำนวนภาพรายวัน</h2>
              {/* <p>แท่งตั้งและเส้นเทรนด์แสดงภาพที่พบการใช้ซ้ำ</p> */}
            </div>
          </div>
          <VerticalTrendChart
            points={imageTrend}
            primaryLabel="ภาพทั้งหมด"
            secondaryLabel="ภาพใช้ซ้ำ"
          />
        </section>
        <section className="panel insight-chart-panel">
          <div className="panel-head">
            <div>
              <h2>จำนวน Customer ID รายวัน</h2>
              {/* <p>นับ Customer ID ไม่ซ้ำภายในแต่ละวัน</p> */}
            </div>
          </div>
          <VerticalTrendChart
            points={customerTrend}
            primaryLabel="Customer ID ทั้งหมด"
            secondaryLabel="Customer ID ใช้ซ้ำ"
          />
        </section>
      </div>

      <section className="panel technician-panel">
        <div className="panel-head">
          <div>
            <h2>Technician ID ที่พบการใช้ภาพซ้ำ</h2>
            {/* <p>เรียงจากจำนวน Customer ID ที่เกี่ยวข้องมากไปน้อย</p> */}
          </div>
          <Network size={20} />
        </div>
        <TechnicianBarChart points={data.insights.technicians} />
      </section>

      <section className="panel export-preview-panel">
        <div className="panel-head">
          <div>
            {/* <p className="eyebrow">EXPORT REPORT</p> */}
            <h2>EXPORT REPORT</h2>
            <p>
              ระบบจะรวมภาพที่ใช้ซ้ำข้ามวันในกลุ่มเดียวกันลง PDF
              ให้อัตโนมัติ
            </p>
          </div>
          <button
            className="primary"
            disabled={!canExport}
            onClick={() => {
              setExporting(true);
              setExportError("");
              void exportDateRangePdf(
                toApiDate(exportDate),
                toApiDate(exportDate),
              )
                .catch(() =>
                  setExportError("สร้าง PDF ไม่สำเร็จ กรุณาลองอีกครั้ง"),
                )
                .finally(() => setExporting(false));
            }}
          >
            <FileDown size={18} />
            {exporting ? "กำลังสร้าง PDF..." : "Export PDF"}
          </button>
        </div>
        <div className="export-date-filter">
          <div className="insight-filter-title">
            <CalendarDays size={19} />
            <div>
              <strong>วันที่สำหรับ Export</strong>
              <span>เลือกวันที่ต้องการออกรายงาน</span>
            </div>
          </div>
          <label>
            วันที่
            <input
              type="date"
              value={exportDate}
              onChange={(event) => setExportDate(event.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={() => setExportDate("")}
            disabled={!exportDate}
          >
            ล้างวันที่
          </button>
        </div>
        {exportError && <p role="alert">{exportError}</p>}
        {preview ? (
          <div className="export-preview-stats">
            <div>
              <span>กลุ่มที่พบการใช้ซ้ำ</span>
              <strong>{preview.group_count.toLocaleString()}</strong>
            </div>
            <div>
              <span>ภาพซ้ำ ณ วันที่เลือก</span>
              <strong>{preview.selected_images.toLocaleString()}</strong>
            </div>
            <div>
              <span>ภาพซ้ำอื่นๆ</span>
              <strong>{preview.cross_date_images.toLocaleString()}</strong>
            </div>
            <div>
              <span>Customer ID ในรายงาน</span>
              <strong>{preview.customer_ids.toLocaleString()}</strong>
            </div>
            <div>
              <span>Technician ID ในรายงาน</span>
              <strong>{preview.technician_ids.toLocaleString()}</strong>
            </div>
          </div>
        ) : (
          <div className="insight-empty">
            {exportDate
              ? "กำลังโหลดข้อมูลสรุป..."
              : "เลือกวันที่เพื่อดูข้อมูลที่จะอยู่ในรายงาน"}
          </div>
        )}
        {preview && (
          <p className="cross-date-note">
            {preview.cross_dates.length ? (
              <>
                พบหลักฐานเชื่อมโยงจากวันอื่น:{" "}
                <b>
                  {preview.cross_dates
                    .map(formatDisplayDate)
                    .filter(Boolean)
                    .join(", ")}
                </b>
              </>
            ) : (
              "ไม่พบภาพหลักฐานข้ามวันที่เลือก"
            )}
          </p>
        )}
        <p className="cross-date-note">
          ยอด Customer ID ของช่างใน PDF เข้าเกณฑ์ใช้รูปภาพซ้ำจากทั้งหมดในระบบ ณ
          เวลา Export เพื่อใช้ตรวจสอบต่อ ไม่ใช่ข้อสรุปว่าช่างทุจริต
        </p>
      </section>
    </section>
  );
}
