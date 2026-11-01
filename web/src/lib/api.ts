export type User = { email: string; name: string; role: "hr" | "admin"; phase: number };

export type CvFile = {
  id: string;
  original_name: string;
  detected_language: string | null;
  status: string;
  reason: string | null;
  ocr_used: boolean;
  output_name: string | null;
  score: number | null;
  strengths?: string | null;
  gaps?: string | null;
};

export type Batch = {
  id: string;
  name: string;
  owner_email: string;
  status: string;
  file_count: number;
  done_count: number;
  scoring: boolean;
  checklist: { must: string[]; nice: string[] } | null;
  checklist_confirmed: boolean;
  retention_mode: string;
  retention_days: number | null;
  retain_until: string | null;
  created_at: string;
  finished_at: string | null;
  eta_seconds: number | null;
  files?: CvFile[];
  ranking?: Array<{
    rank: number;
    name: string;
    score: number;
    must_label: string;
    strengths: string;
    gaps: string;
    file: string | null;
    file_id: string;
  }>;
};

async function parse(response: Response) {
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : "The request failed.");
  }
  return body;
}

export async function api(path: string, init: RequestInit = {}) {
  const response = await fetch(`/backend${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...init.headers },
  });
  return parse(response);
}

export function statusClass(status: string) {
  if (status === "Done") return "done";
  if (status === "Needs review") return "review";
  if (status === "Failed") return "failed";
  return "";
}
