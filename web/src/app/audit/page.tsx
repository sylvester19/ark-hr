"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { api } from "@/lib/api";

type Row = { id: number; at: string; actor: string; action: string; batch_id: string | null; file_count: number | null };

export default function AuditPage() {
  return (
    <Shell>
      <Log />
    </Shell>
  );
}

function Log() {
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    api("/audit").then((body) => setRows(body.rows));
  }, []);
  return (
    <div>
      <h1>Audit log</h1>
      <p className="lede">Who uploaded, downloaded, or deleted a batch. Candidate CV text is not stored here.</p>
      <table>
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>Action</th>
            <th>Batch</th>
            <th>Files</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.at.replace("T", " ").slice(0, 16)}</td>
              <td>{row.actor}</td>
              <td>{row.action}</td>
              <td>{row.batch_id || "—"}</td>
              <td>{row.file_count ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
