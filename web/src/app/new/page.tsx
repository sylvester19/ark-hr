"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { api, type User } from "@/lib/api";

export default function NewBatchPage() {
  return (
    <Shell>
      <Form />
    </Shell>
  );
}

function Form() {
  const router = useRouter();
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [score, setScore] = useState(false);
  const [jobText, setJobText] = useState("");
  const [jobFile, setJobFile] = useState<File | null>(null);
  const [phase, setPhase] = useState(1);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api("/auth/me").then((user: User) => setPhase(user.phase));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!files.length) {
      setError("Add a zip or at least one CV.");
      return;
    }
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    body.append("name", name);
    body.append("score", score ? "true" : "false");
    body.append("job_text", jobText);
    if (jobFile) body.append("job_file", jobFile);
    setBusy(true);
    try {
      const batch = await api("/batches", { method: "POST", body });
      router.push(`/batches/${batch.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <h1>New batch</h1>
      <p className="lede">Drop the CVs. Download one zip of English CVs when the batch is ready.</p>
      <div className="card">
        <label htmlFor="files">CVs (.zip, .docx, .doc, .pdf, .jpg, .png) — 100 files or 200 MB</label>
        <div className="drop">
          <input
            id="files"
            type="file"
            multiple
            accept=".zip,.docx,.doc,.pdf,.jpg,.jpeg,.png"
            onChange={(event) => setFiles(Array.from(event.target.files || []))}
          />
          <p>{files.length ? `${files.length} file${files.length === 1 ? "" : "s"} selected` : "Or choose files"}</p>
        </div>
        <div className="row">
          <div style={{ flex: 1 }}>
            <label htmlFor="name">Batch name</label>
            <input
              id="name"
              type="text"
              placeholder="Batch 2026-10-27 14:30"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
        </div>
        {phase >= 2 && (
          <>
            <div className="check">
              <input id="score" type="checkbox" checked={score} onChange={(event) => setScore(event.target.checked)} />
              <label htmlFor="score">Score against a job</label>
            </div>
            {score && (
              <>
                <label htmlFor="job">Job description</label>
                <textarea id="job" value={jobText} onChange={(event) => setJobText(event.target.value)} />
                <div style={{ marginTop: 8 }}>
                  <input type="file" accept=".txt,.docx,.pdf" onChange={(event) => setJobFile(event.target.files?.[0] || null)} />
                </div>
              </>
            )}
          </>
        )}
        {error && <p className="error">{error}</p>}
        <div className="row">
          <button className="primary" disabled={busy} type="submit">
            {busy ? "Uploading…" : "Translate to English"}
          </button>
        </div>
      </div>
    </form>
  );
}
