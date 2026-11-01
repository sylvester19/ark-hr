"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [config, setConfig] = useState<{ microsoft: boolean; local: boolean } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("error") === "access" || params.get("error") === "auth_failed") {
      setError("Authentication failed.");
    }
    if (params.get("error") === "session_expired") {
      setError("Session expired. Sign in again.");
    }
    fetch("/backend/auth/config")
      .then((response) => response.json())
      .then(setConfig);
  }, []);

  async function microsoft() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/backend/auth/login", { credentials: "include" });
      if (!response.ok) throw new Error("Failed to initiate login");
      const data = await response.json();
      if (!data.url) throw new Error("Microsoft login URL not returned");
      window.location.href = data.url;
    } catch {
      setBusy(false);
      setError("Something went wrong. Try again.");
    }
  }

  return (
    <main className="login-split">
      <section className="login-form">
        <div className="login-inner">
          <img src="/logo-icon.svg" alt="ARK IMPEX" width={36} height={36} />
          <h1>Sign in</h1>
          <p className="login-sub">Bulk CV translation for Group Arkays</p>
          <button className="ms-btn" onClick={microsoft} disabled={busy || !config?.microsoft}>
            <svg viewBox="0 0 23 23" aria-hidden="true">
              <path d="M11.4 24H0V12.6h11.4V24zM24 24H12.6V12.6H24V24zM11.4 11.4H0V0h11.4v11.4zM24 11.4H12.6V0H24v11.4z" fill="currentColor" />
            </svg>
            {busy ? "Redirecting…" : "Continue with Microsoft"}
          </button>
          {!config?.microsoft && config && (
            <p className="error">Microsoft sign-in is not configured on this server.</p>
          )}
          {error && <p className="login-error">{error}</p>}
          {config?.local && !config.microsoft && (
            <button
              className="ghost"
              style={{ marginTop: 16, width: "100%" }}
              onClick={async () => {
                const response = await fetch("/backend/auth/local", { method: "POST", credentials: "include" });
                if (response.ok) router.push("/new");
              }}
            >
              Continue on this PC
            </button>
          )}
        </div>
      </section>
      <section className="login-brand">
        <div className="bg-grid bg-glow" />
        <div className="brand-copy">
          <span>ARK HR</span>
          <h2>
            CVs in.
            <br />
            English out.
          </h2>
          <p>One zip of clean English CVs, in the standard template.</p>
        </div>
        <div className="brand-foot">
          <span>Upload</span>
          <i />
          <span>Translate</span>
          <i />
          <span>Download</span>
        </div>
      </section>
    </main>
  );
}
