"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { api } from "@/lib/api";

export default function SettingsPage() {
  return (
    <Shell>
      <Settings />
    </Shell>
  );
}

function Settings() {
  const [choice, setChoice] = useState("forever");
  const [days, setDays] = useState(14);
  const [purgeDays, setPurgeDays] = useState(30);
  const [preview, setPreview] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    api("/settings").then((body) => {
      if (body.retention_mode === "forever") setChoice("forever");
      else if ([7, 30, 90, 180, 365].includes(body.retention_days)) setChoice(String(body.retention_days));
      else {
        setChoice("custom");
        setDays(body.retention_days || 14);
      }
    });
  }, []);

  return (
    <div>
      <h1>Settings</h1>
      <p className="lede">How long new batches are kept. This is not hard-coded.</p>
      <div className="card">
        <label>Default retention for new batches</label>
        <select value={choice} onChange={(event) => setChoice(event.target.value)}>
          <option value="forever">Keep forever</option>
          <option value="7">7 days</option>
          <option value="30">30 days</option>
          <option value="90">3 months</option>
          <option value="180">6 months</option>
          <option value="365">1 year</option>
          <option value="custom">Custom</option>
        </select>
        {choice === "custom" && (
          <input type="number" min={1} value={days} onChange={(event) => setDays(Number(event.target.value))} style={{ marginTop: 8 }} />
        )}
        <button
          className="primary"
          style={{ marginTop: 12 }}
          onClick={async () => {
            await api("/settings", { method: "PUT", body: JSON.stringify({ choice, days }) });
            setMessage("Saved. New batches use this retention.");
          }}
        >
          Save
        </button>
        {message && <p>{message}</p>}
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Delete old batches</h2>
        <label>Older than (days)</label>
        <input type="number" min={1} value={purgeDays} onChange={(event) => setPurgeDays(Number(event.target.value))} />
        <div className="row">
          <button
            className="ghost"
            onClick={async () => {
              const body = await api("/settings/purge", {
                method: "POST",
                body: JSON.stringify({ days: purgeDays, confirm: false }),
              });
              setPreview(`${body.batches} batches and ${body.files} files will be deleted.`);
            }}
          >
            Preview
          </button>
          <button
            className="danger"
            disabled={!preview}
            onClick={async () => {
              const body = await api("/settings/purge", {
                method: "POST",
                body: JSON.stringify({ days: purgeDays, confirm: true }),
              });
              setPreview("");
              setMessage(`Deleted ${body.batches} batches and ${body.files} files from storage.`);
            }}
          >
            Delete them
          </button>
        </div>
        {preview && <p className="note">{preview}</p>}
      </div>
    </div>
  );
}
