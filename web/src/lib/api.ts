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

function plainError(status: number, detail: string) {
  const text = detail.replace(/\s+/g, " ").trim();
  const lower = text.toLowerCase();
  if (!text || lower.includes("json") || lower.includes("syntaxerror") || lower.includes("unexpected token")) {
    if (status === 413 || lower.includes("too large") || lower.includes("exceeded")) {
      return "This upload is too large. Send one zip, or fewer than 100 CVs, and stay under 200 MB.";
    }
    return "Those files could not be uploaded. Send one zip, or fewer files, and try again.";
  }
  if (lower.includes("part exceeded") || lower.includes("maximum size")) {
    return "One of those files is too large on its own. Put the CVs in one zip under 200 MB.";
  }
  return text;
}

function detailMessage(status: number, body: unknown, raw: string) {
  const detail = body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : null;
  if (typeof detail === "string") return plainError(status, detail);
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : ""))
      .filter(Boolean);
    if (messages.length) return plainError(status, messages.join(" "));
  }
  if (status === 413) return plainError(413, "too large");
  if (status === 401) return "Sign in with Microsoft, then try again.";
  if (status >= 500 || !raw.trim().startsWith("{")) return plainError(status, raw);
  return "The request failed.";
}

async function parse(response: Response): Promise<any> {
  const text = await response.text();
  let body: unknown = {};
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      if (!response.ok) throw new Error(detailMessage(response.status, null, text));
      throw new Error("The server sent a reply this page could not read. Refresh and try again.");
    }
  }
  if (!response.ok) throw new Error(detailMessage(response.status, body, text));
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

export function localWhen(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.replace("T", " ").slice(0, 16);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
