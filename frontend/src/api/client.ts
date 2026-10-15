export type RelationshipResult = {
  score: number;
  decision: string;
  classification: string;
  reuse_verdict: "reused" | "review" | "not_reused";
  reasons: string[];
  evidence: Record<string, unknown>;
  visualizations: Record<string, string>;
};

// Downloading a large PDF through Vite's development proxy can be terminated
// after a 200 response. In development call FastAPI directly; production
// keeps the relative API URL for its reverse proxy.
const API_ORIGIN = import.meta.env.DEV ? "http://127.0.0.1:8000" : "";
const API = `${API_ORIGIN}/api/v1`;

export async function compareImages(first: File, second: File): Promise<RelationshipResult> {
  const body = new FormData();
  body.append("image_a", first);
  body.append("image_b", second);
  const response = await fetch(`${API}/compare`, { method: "POST", body });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: "ไม่สามารถวิเคราะห์ภาพได้" }));
    throw new Error(error.message ?? error.detail ?? "ไม่สามารถวิเคราะห์ภาพได้");
  }
  return response.json();
}

export async function compareStoredImages(imageAId: string, imageBId: string): Promise<RelationshipResult> {
  const response = await fetch(`${API}/compare/stored`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image_a_id: imageAId, image_b_id: imageBId }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: "ไม่สามารถวิเคราะห์ภาพจากคลังได้" }));
    throw new Error(error.message ?? error.detail ?? "ไม่สามารถวิเคราะห์ภาพจากคลังได้");
  }
  return response.json();
}

export async function getStoredImageFile(imageId: string): Promise<File> {
  const safeId = encodeURIComponent(imageId);
  const [detailResponse, contentResponse] = await Promise.all([
    fetch(`${API}/images/${safeId}`),
    fetch(`${API}/images/${safeId}/content`),
  ]);
  if (!detailResponse.ok || !contentResponse.ok) throw new Error("โหลดภาพจากคลังไม่สำเร็จ");
  const detail = await detailResponse.json() as { original_filename?: string; mime_type?: string };
  const blob = await contentResponse.blob();
  return new File([blob], detail.original_filename || `${imageId}.img`, {
    type: detail.mime_type || blob.type || "application/octet-stream",
  });
}

export type StoredImageDetail = {
  original_filename: string;
  mime_type: string;
};

export async function getStoredImageDetail(imageId: string): Promise<StoredImageDetail> {
  const response = await fetch(`${API}/images/${encodeURIComponent(imageId)}`);
  if (!response.ok) throw new Error("โหลดรายละเอียดภาพจากคลังไม่สำเร็จ");
  return response.json() as Promise<StoredImageDetail>;
}

export type ExportableBbid = { bbid: string; image_count: number; dates: string[]; related_customer_ids: string[]; exported: boolean };

export async function getExportableBbids(dateFrom: string, dateTo: string, search = ""): Promise<{ items: ExportableBbid[] }> {
  const query = new URLSearchParams({ date_from: dateFrom, date_to: dateTo, search });
  const response = await fetch(`${API}/exports/bbids?${query}`);
  if (!response.ok) throw new Error("โหลดรายการ BBID สำหรับ Export ไม่สำเร็จ");
  return response.json();
}

export async function exportBbidsPdf(customerIds: string[], dateFrom: string, dateTo: string): Promise<void> {
  const response = await fetch(`${API}/exports/pdf`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ customer_ids: customerIds, date_from: dateFrom, date_to: dateTo }) });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "สร้าง PDF ไม่สำเร็จ" }));
    throw new Error(error.detail ?? "สร้าง PDF ไม่สำเร็จ");
  }
  const payload = await response.json() as { download_url: string };
  // Let the browser navigate to the PDF response directly instead of reading
  // a large PDF stream with fetch. This avoids ERR_FAILED after HTTP 200.
  window.location.assign(`${API_ORIGIN}${payload.download_url}`);
}

/** Export every detected relationship group that has evidence in the date range. */
export function exportDateRangePdf(dateFrom: string, dateTo: string): Promise<void> {
  return exportBbidsPdf([], dateFrom, dateTo);
}

export type DashboardData = {
  total_images: number;
  related_pairs: number;
  pending_jobs: number;
  failed_jobs: number;
  images_in_system: number;
  reused_images: number;
  total_jobs: number;
  reused_jobs: number;
  duplicate_jobs: Array<{ job_number: string; images_in_system: number; reused_images: number; evidence_links: number }>;
  insights: DashboardInsights;
};

export type DashboardInsights = {
  daily: Array<{
    date: string;
    total_images: number;
    reused_images: number;
    total_customer_ids: number;
    reused_customer_ids: number;
  }>;
  technicians: Array<{ technician_id: string; reused_customer_ids: number }>;
  export_preview: {
    group_count: number;
    selected_images: number;
    report_images: number;
    cross_date_images: number;
    customer_ids: number;
    technician_ids: number;
    cross_dates: string[];
  };
};

export async function getDashboard(dateFrom?: string, dateTo?: string): Promise<DashboardData> {
  const query = new URLSearchParams();
  if (dateFrom) query.set("date_from", dateFrom);
  if (dateTo) query.set("date_to", dateTo);
  const response = await fetch(`${API}/dashboard${query.size ? `?${query}` : ""}`);
  if (!response.ok) throw new Error("โหลดข้อมูลสรุปไม่สำเร็จ");
  return response.json();
}

export function downloadDashboardReport(totalImages: number) {
  window.location.href = `${API}/dashboard/report.xlsx?total_images=${Math.max(0, Math.trunc(totalImages))}`;
}

export async function createBatch(files: File[]): Promise<{ job_id: string; status: string; file_count: number }> {
  const body = new FormData();
  files.forEach(file => body.append("files", file));
  const response = await fetch(`${API}/batches`, { method: "POST", body });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "อัปโหลดไม่สำเร็จ" }));
    throw new Error(error.message ?? error.detail ?? "อัปโหลดไม่สำเร็จ");
  }
  return response.json();
}

export async function reanalyzeLibrary(): Promise<{ job_id: string; status: string; file_count: number }> {
  const response = await fetch(`${API}/batches/reanalyze`, { method: "POST" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "เริ่มวิเคราะห์ใหม่ไม่สำเร็จ" }));
    throw new Error(error.message ?? error.detail ?? "เริ่มวิเคราะห์ใหม่ไม่สำเร็จ");
  }
  return response.json();
}

export type BatchJob = { id: string; status: string; total: number; processed: number; error: string | null; started_at?: string | null; completed_at?: string | null; duration_seconds?: number | null };

export async function getJob(jobId: string): Promise<BatchJob> {
  const response = await fetch(`${API}/jobs/${jobId}`);
  if (!response.ok) throw new Error("โหลดสถานะงานไม่สำเร็จ");
  return response.json();
}

export async function cancelJob(jobId: string): Promise<BatchJob> {
  const response = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  if (!response.ok) throw new Error("หยุดการวิเคราะห์ไม่สำเร็จ");
  return response.json();
}

export async function resumeJob(jobId: string): Promise<BatchJob> {
  const response = await fetch(`${API}/jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
  if (!response.ok) throw new Error("ทำต่อจากจุดเดิมไม่สำเร็จ");
  return response.json();
}

export async function getActiveJob(): Promise<BatchJob | null> {
  const response = await fetch(`${API}/jobs/active`);
  if (!response.ok) throw new Error("โหลดงานที่กำลังทำอยู่ไม่สำเร็จ");
  return response.json();
}

export type RelationshipSubgroup = {
  id: number;
  source_ids: string[];
  image_ids: string[];
  size: number;
  images: Array<{
    id: string;
    filename: string;
    technician_id: string | null;
    job_number: string | null;
    checkin_date: string | null;
    width: number;
    height: number;
    url: string;
  }>;
  relationships: Array<{ image_a_id: string; image_b_id: string; score: number; classification: string }>;
};

export type ImageGroup = {
  id: number;
  source_ids: string[];
  technician_ids: string[];
  size: number;
  relationship_count: number;
  subgroups: RelationshipSubgroup[];
};

export async function getGroups(): Promise<{ groups: ImageGroup[] }> {
  const response = await fetch(`${API}/groups`);
  if (!response.ok) throw new Error("โหลดกลุ่มภาพไม่สำเร็จ");
  return response.json();
}
