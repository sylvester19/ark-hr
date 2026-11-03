"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { api, statusClass, type Batch, type CvFile } from "@/lib/api";

export default function BatchPage() {
  return (
    <Shell>
      <Detail />
    </Shell>
  );
}

function FileNote({ file }: { file: CvFile }) {
  const [open, setOpen] = useState(false);
  const parts = [file.ocr_used ? "OCR used." : "", file.reason || ""].filter(Boolean);
  if (!parts.length) return null;
  return (
    <span className="file-note">
      <button
        type="button"
        className="note-btn"
        aria-expanded={open}
        aria-label={open ? "Hide the note" : "Show the note"}
        title={open ? "Hide the note" : "Show the note"}
        onClick={() => setOpen((value) => !value)}
      >
        !
      </button>
      {open && <span className="note">{parts.join(" ")}</span>}
    </span>
  );
}

function Detail() {
  const params = useParams<{ id: string }>();
  const [batch, setBatch] = useState<Batch | null>(null);
  const [error, setError] = useState("");
  const [onlyReview, setOnlyReview] = useState(false);
  const [must, setMust] = useState("");
  const [nice, setNice] = useState("");

  async function load() {
    const body = await api(`/batches/${params.id}`);
    setBatch(body);
    if (body.checklist && !must && !nice) {
      setMust(body.checklist.must.join("\n"));
      setNice(body.checklist.nice.join("\n"));
    }
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    const timer = setInterval(() => {
      load().catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
    // The checklist text is seeded once. Later edits must not be overwritten.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  if (error) return <p className="error">{error}</p>;
  if (!batch) return <p>Loading…</p>;

  const total = batch.file_count || 1;
  const width = Math.round((batch.done_count / total) * 100);
  const files = (batch.files || []).filter((file) => !onlyReview || file.status === "Needs review" || file.status === "Failed");

  async function download(path: string) {
    const link = await api(path, { method: "POST" });
    window.location.href = `/backend${link.url}`;
  }

  return (
    <div>
      <h1>{batch.name}</h1>
      <p className="lede">
        {batch.done_count} of {batch.file_count} finished
        {batch.eta_seconds ? ` · about ${Math.ceil(batch.eta_seconds / 60)} min left` : ""}
      </p>
      <div className="bar">
        <span style={{ width: `${width}%` }} />
      </div>
      <div className="row">
        <button className="primary" disabled={batch.done_count === 0} onClick={() => download(`/batches/${batch.id}/link`)}>
          Download all (zip)
        </button>
        <label className="check" style={{ margin: 0 }}>
          <input type="checkbox" checked={onlyReview} onChange={(event) => setOnlyReview(event.target.checked)} />
          Needs review
        </label>
      </div>

      {batch.scoring && batch.checklist && !batch.checklist_confirmed && (
        <div className="card" style={{ marginTop: 20 }}>
          <h2>Job checklist</h2>
          <p className="lede">Edit the list, then score. Nothing is rejected automatically.</p>
          <label>Must-haves</label>
          <textarea value={must} onChange={(event) => setMust(event.target.value)} />
          <label style={{ marginTop: 12 }}>Nice-to-haves</label>
          <textarea value={nice} onChange={(event) => setNice(event.target.value)} />
          <button
            className="primary"
            style={{ marginTop: 12 }}
            onClick={async () => {
              await api(`/batches/${batch.id}/checklist`, {
                method: "PUT",
                body: JSON.stringify({
                  must: must.split("\n").map((line) => line.trim()).filter(Boolean),
                  nice: nice.split("\n").map((line) => line.trim()).filter(Boolean),
                  confirm: true,
                }),
              });
              await load();
            }}
          >
            Score with this checklist
          </button>
        </div>
      )}

      {!!batch.ranking?.length && (
        <div className="card" style={{ marginTop: 20 }}>
          <h2>Job match</h2>
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Candidate</th>
                <th>Score</th>
                <th>Must-haves</th>
                <th>Strengths</th>
                <th>Gaps</th>
              </tr>
            </thead>
            <tbody>
              {batch.ranking.map((row) => (
                <tr key={row.file_id}>
                  <td>{row.rank}</td>
                  <td>{row.name}</td>
                  <td>{row.score}</td>
                  <td>{row.must_label}</td>
                  <td>{row.strengths}</td>
                  <td>{row.gaps}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <table style={{ marginTop: 20 }}>
        <thead>
          <tr>
            <th>File</th>
            <th>Language</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {files.map((file) => (
            <tr key={file.id}>
              <td>
                {file.original_name}
                <FileNote file={file} />
              </td>
              <td>{file.detected_language || "—"}</td>
              <td>
                <span className={`badge ${statusClass(file.status)}`}>{file.status}</span>
              </td>
              <td>
                {file.output_name && (
                  <button className="ghost" onClick={() => download(`/batches/${batch.id}/files/${file.id}/link`)}>
                    Download
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
