# ARK HR – Bulk CV Translation Tool

HR drops in a zip or a set of CVs and downloads one zip of English CVs in a plain Word template. The module sits beside ARK IMPEX. It is not wired into the live ARK IMPEX sidebar yet.

## Run on this PC

```powershell
cd "F:\Hostwire Systems\Group Arkays\DTE\Translation tool\ark-hr"
copy .env.example .env
.\.venv\Scripts\python.exe -m ark_hr.api
```

In a second window:

```powershell
cd web
npm install
npm run dev
```

Open http://localhost:3215 and choose **Continue with Microsoft**. Sign-in uses the same Entra app and the same redirect as ARK IMPEX core: `http://localhost:3000/auth/callback`. The API listens on port 3000, so stop the ARK IMPEX API before starting this one. Nothing in the ARK IMPEX repo is changed.

The default is Phase 2 (`ARK_HR_PHASE=2`): Word, PDF, and image CVs, checks, progress, zip, history, delete, job-match scoring, retention, the daily purge, the ready email, and the audit screen. Set `ARK_HR_PHASE=1` to hide the Phase 2 screens. The ready email stays off until `ARK_HR_GRAPH_SENDER` is a mailbox this app may send from. Settings, audit, and bulk delete stay limited to `ARK_HR_ADMIN_EMAILS`.

## What the checks enforce

- Emails, phone numbers, URLs, and career years in the original must appear in the English CV.
- Nothing of that kind may be added.
- The candidate name, employer, school, issuer, and place names must match the original spelling.
- The English CV must stay within 0.6–1.6× the original word count.
- A birth year is left out on purpose and does not fail the check.
- One automatic retry, then **Needs review**, and the CV is still produced.
- A bad file does not stop the rest of the batch.
- The scoring model is not given the name, phone, email, photo, age, gender, nationality, religion, or marital status.
- CV text is not written to the audit log. Downloads expire after 15 minutes.
- The model URL is refused if it points at OpenAI, Google, DeepL, Anthropic, or any public host.

Tests: `.\.venv\Scripts\python.exe -m pytest`

## What translates the CVs

The same path runs on this PC, on Linux, and in Docker. CV text stays on the machine. Nothing is sent to OpenAI, Google, DeepL, or any other public model.

- The translator is an open-source LLM at temperature 0, with the brief’s JSON schema. Qwen2.5-1.5B-Instruct (Apache-2.0) runs in-process from `data/models/qwen2.5-1.5b-instruct-q4_k_m.gguf`. Download that file once from `https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf` (about 1.1 GB). Set `ARK_HR_MODEL` to use a private Ollama or vLLM model instead, including a larger one after a written cost quote.
- On this PC, one French sample took 71 seconds for the first pass and 161 seconds when a second pass was needed. Names stayed as written. A second pass that still leaves a French sentence is marked Needs review. That is one file, not the 30-CV timing target.
- `.doc` files are converted with LibreOffice. Microsoft Word is used only when LibreOffice is not installed.
- Scans are read with Tesseract (`fra+eng+ara+por`). Windows OCR is used only when Tesseract is not installed.
- The 1.5B model is the portable CPU choice. It is not a measured stand-in for the 30-CV / 60-minute target. Report a timed run before promising that target.

## Before this can go live

See the list in the project note from Hostwire. The short version: Entra groups, a redirect URI on the existing ARK IMPEX app, Azure Blob in UAE North, a benchmarked open-source model on Group Arkays hardware, LibreOffice and Tesseract on that server, and a Graph mailbox for the ready email.
