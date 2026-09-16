export type RelationshipResult = {
  score: number;
  decision: string;
  classification: string;
  reuse_verdict: "reused" | "review" | "not_reused";
  reasons: string[];
  evidence: Record<string, unknown>;
  visualizations: Record<string, string>;
};

const API = "/api/v1";

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

export async function getDashboard() {
  const response = await fetch(`${API}/dashboard`);
  if (!response.ok) throw new Error("โหลดข้อมูลสรุปไม่สำเร็จ");
  return response.json();
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

export type BatchJob = { id: string; status: string; total: number; processed: number; error: string | null };

export async function getJob(jobId: string): Promise<BatchJob> {
  const response = await fetch(`${API}/jobs/${jobId}`);
  if (!response.ok) throw new Error("โหลดสถานะงานไม่สำเร็จ");
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
  images: Array<{ id: string; filename: string; width: number; height: number; url: string }>;
  relationships: Array<{ image_a_id: string; image_b_id: string; score: number; classification: string }>;
};

export type ImageGroup = {
  id: number;
  source_ids: string[];
  size: number;
  relationship_count: number;
  subgroups: RelationshipSubgroup[];
};

export async function getGroups(): Promise<{ groups: ImageGroup[] }> {
  const response = await fetch(`${API}/groups`);
  if (!response.ok) throw new Error("โหลดกลุ่มภาพไม่สำเร็จ");
  return response.json();
}
