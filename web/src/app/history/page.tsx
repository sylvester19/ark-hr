"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { api, localWhen, type Batch, type User } from "@/lib/api";

export default function HistoryPage() {
  return (
    <Shell>
      <History />
    </Shell>
  );
}

function History() {
  const [rows, setRows] = useState<Batch[]>([]);
  const [admin, setAdmin] = useState(false);
  const [phase, setPhase] = useState(1);
  const [error, setError] = useState("");

  async function load() {
    const [me, list]: [User, { batches: Batch[] }] = await Promise.all([api("/auth/me"), api("/batches")]);
    setAdmin(me.role === "admin");
    setPhase(me.phase);
    setRows(list.batches);
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  const pending = rows.some((row) => row.status === "queued" || row.status === "running");
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      load().catch((err) => setError(err.message));
    }, 5000);
    return () => window.clearInterval(timer);
  }, [pending]);

  return (
    <div>
      <h1>History</h1>
      <p className="lede">{admin ? "Every batch." : "Your batches."}</p>
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>Batch</th>
            <th>When</th>
            <th>Uploader</th>
            <th>Files</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <Link href={`/batches/${row.id}`}>{row.name}</Link>
              </td>
              <td>{localWhen(row.created_at)}</td>
              <td>{row.owner_email}</td>
              <td>{row.file_count}</td>
              <td>{row.status}</td>
              <td>
                <button
                  className="danger"
                  onClick={async () => {
                    if (!window.confirm(`Delete ${row.name}? The files are removed from storage.`)) return;
                    await api(`/batches/${row.id}`, { method: "DELETE" });
                    await load();
                  }}
                >
                  Delete
                </button>
                {admin && phase >= 2 && (
                  <select
                    style={{ marginLeft: 8, width: "auto" }}
                    value={row.retention_mode === "forever" ? "forever" : String(row.retention_days || "30")}
                    onChange={async (event) => {
                      await api(`/batches/${row.id}/retention`, {
                        method: "PATCH",
                        body: JSON.stringify({ choice: event.target.value }),
                      });
                      await load();
                    }}
                  >
                    <option value="forever">Keep forever</option>
                    <option value="7">7 days</option>
                    <option value="30">30 days</option>
                    <option value="90">3 months</option>
                    <option value="180">6 months</option>
                    <option value="365">1 year</option>
                  </select>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
