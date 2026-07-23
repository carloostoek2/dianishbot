#!/usr/bin/env python3
"""Local one-card training example reviewer for diana_training.db.

  python scripts/review_training.py
  # open http://127.0.0.1:8765

Keyboard (in the page): A = approve (keep), D = discard (delete), Space = next action focus.

Progress is sequential (id ascending) and stored in diana_review_progress.json so approved
items are not re-shown. Discard deletes the row. Use --reset to start the queue over.
Binds to 127.0.0.1 only — training data is sensitive.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = REPO_ROOT / "diana_training.db"
DEFAULT_PROGRESS = REPO_ROOT / "diana_review_progress.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
CONTEXT_TAIL = 8  # messages shown in the card


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_progress(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"after_id": 0, "approved": 0, "discarded": 0, "updated_at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"after_id": 0, "approved": 0, "discarded": 0, "updated_at": None}
    return {
        "after_id": int(data.get("after_id") or 0),
        "approved": int(data.get("approved") or 0),
        "discarded": int(data.get("discarded") or 0),
        "updated_at": data.get("updated_at"),
    }


def save_progress(path: Path, progress: dict[str, Any]) -> None:
    progress = {
        "after_id": int(progress.get("after_id") or 0),
        "approved": int(progress.get("approved") or 0),
        "discarded": int(progress.get("discarded") or 0),
        "updated_at": utc_now(),
    }
    path.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def parse_context(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "?")
        content = str(item.get("content") or "")
        out.append({"role": role, "content": content})
    return out


def row_to_card(row: sqlite3.Row) -> dict[str, Any]:
    context = parse_context(row["context"])
    tail = context[-CONTEXT_TAIL:] if context else []
    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "username": row["username"] or "",
        "ts": row["ts"] or "",
        "topic": row["topic"] or "",
        "status": row["status"] or "",
        "rating": row["rating"] or "",
        "confidence": row["confidence"],
        "bot_response": row["bot_response"] or "",
        "correction": row["correction"] or "",
        "context": tail,
        "context_total": len(context),
        "context_shown": len(tail),
    }


def get_stats(conn: sqlite3.Connection, after_id: int) -> dict[str, Any]:
    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM examples WHERE id > ?",
        (after_id,),
    ).fetchone()["n"]
    total = conn.execute("SELECT COUNT(*) AS n FROM examples").fetchone()["n"]
    return {
        "remaining": remaining,
        "total_in_db": total,
        "after_id": after_id,
    }


def get_next(conn: sqlite3.Connection, after_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, chat_id, username, ts, context, bot_response, confidence,
               topic, rating, correction, status
        FROM examples
        WHERE id > ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (after_id,),
    ).fetchone()
    if row is None:
        return None
    return row_to_card(row)


def approve_example(conn: sqlite3.Connection, example_id: int) -> bool:
    """Keep the row. Pending drafts become usable few-shots (reviewed + good)."""
    row = conn.execute(
        "SELECT id, status, rating FROM examples WHERE id = ?",
        (example_id,),
    ).fetchone()
    if row is None:
        return False
    status = (row["status"] or "").strip().lower()
    rating = (row["rating"] or "").strip().lower()
    if status == "pending" or not rating:
        conn.execute(
            """
            UPDATE examples
            SET status = 'reviewed',
                rating = CASE
                    WHEN rating IS NULL OR rating = '' THEN 'good'
                    ELSE rating
                END
            WHERE id = ?
            """,
            (example_id,),
        )
        conn.commit()
    return True


def discard_example(conn: sqlite3.Connection, example_id: int) -> bool:
    cur = conn.execute("DELETE FROM examples WHERE id = ?", (example_id,))
    conn.commit()
    return cur.rowcount > 0


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Diana — Review training</title>
  <style>
    :root {
      --bg: #0f1115;
      --card: #1a1d24;
      --text: #e8eaed;
      --muted: #9aa0a6;
      --border: #2a2f3a;
      --good: #1f6f43;
      --good-h: #258a53;
      --bad: #8b2e2e;
      --bad-h: #a83838;
      --accent: #6ea8fe;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      padding: 0.9rem 1.25rem;
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      background: rgba(15,17,21,0.95);
      backdrop-filter: blur(6px);
      z-index: 2;
    }
    header h1 {
      margin: 0;
      font-size: 1rem;
      font-weight: 600;
      letter-spacing: 0.02em;
    }
    .stats {
      display: flex;
      gap: 1rem;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 0.9rem;
    }
    .stats strong { color: var(--text); }
    main {
      max-width: 880px;
      margin: 0 auto;
      padding: 1.25rem;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 1.1rem 1.2rem 1.25rem;
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 0.55rem 1rem;
      color: var(--muted);
      font-size: 0.85rem;
      margin-bottom: 1rem;
    }
    .meta span b { color: var(--text); font-weight: 600; }
    .section-title {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin: 0 0 0.5rem;
    }
    .messages {
      display: flex;
      flex-direction: column;
      gap: 0.55rem;
      margin-bottom: 1.1rem;
      max-height: 48vh;
      overflow: auto;
      padding-right: 0.25rem;
    }
    .msg {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.65rem 0.8rem;
      background: #14171d;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.45;
    }
    .msg .role {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--accent);
      margin-bottom: 0.3rem;
    }
    .msg.user .role { color: #9ad0ff; }
    .msg.assistant .role { color: #b6f0c2; }
    .response {
      border: 1px solid #2f4a36;
      background: #142018;
      border-radius: 10px;
      padding: 0.85rem 0.95rem;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.5;
      font-size: 1.05rem;
    }
    .correction {
      margin-top: 0.75rem;
      border: 1px solid #4a3a20;
      background: #1c170f;
      border-radius: 10px;
      padding: 0.75rem 0.9rem;
      white-space: pre-wrap;
      color: #f0d9a8;
    }
    .actions {
      display: flex;
      gap: 0.75rem;
      margin-top: 1.2rem;
      position: sticky;
      bottom: 0;
      padding: 0.75rem 0 0.2rem;
      background: linear-gradient(to top, var(--bg) 70%, transparent);
    }
    button {
      flex: 1;
      border: 0;
      border-radius: 12px;
      padding: 0.95rem 1rem;
      font-size: 1rem;
      font-weight: 650;
      cursor: pointer;
      color: white;
      transition: background 0.12s ease, transform 0.05s ease;
    }
    button:active { transform: scale(0.985); }
    button:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }
    .approve { background: var(--good); }
    .approve:hover:not(:disabled) { background: var(--good-h); }
    .discard { background: var(--bad); }
    .discard:hover:not(:disabled) { background: var(--bad-h); }
    .hint {
      margin-top: 0.85rem;
      color: var(--muted);
      font-size: 0.82rem;
      text-align: center;
    }
    .empty, .error {
      text-align: center;
      padding: 3rem 1rem;
      color: var(--muted);
    }
    .error { color: #ffb4b4; }
    kbd {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      border: 1px solid var(--border);
      border-bottom-width: 2px;
      border-radius: 6px;
      padding: 0.05rem 0.35rem;
      background: #12151b;
      color: var(--text);
      font-size: 0.78rem;
    }
  </style>
</head>
<body>
  <header>
    <h1>Diana · review training</h1>
    <div class="stats" id="stats">Cargando…</div>
  </header>
  <main>
    <div id="root" class="empty">Cargando…</div>
  </main>
  <script>
    const root = document.getElementById('root');
    const statsEl = document.getElementById('stats');
    let current = null;
    let busy = false;

    function esc(s) {
      return String(s ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
    }

    function renderStats(s) {
      if (!s) return;
      statsEl.innerHTML = `
        <span>Quedan <strong>${s.remaining}</strong></span>
        <span>En DB <strong>${s.total_in_db}</strong></span>
        <span>Aprobados <strong>${s.approved ?? 0}</strong></span>
        <span>Descartados <strong>${s.discarded ?? 0}</strong></span>
      `;
    }

    function renderEmpty(stats) {
      current = null;
      root.className = 'empty';
      root.innerHTML = `
        <h2 style="color:var(--text);margin:0 0 .5rem">Listo</h2>
        <p>No quedan ejemplos por revisar en esta cola.</p>
        <p style="font-size:.9rem">Aprobados: ${stats?.approved ?? 0} · Descartados: ${stats?.discarded ?? 0}</p>
      `;
    }

    function renderCard(item, stats) {
      current = item;
      root.className = '';
      const msgs = (item.context || []).map(m => {
        const role = esc(m.role);
        return `<div class="msg ${role}"><div class="role">${role}</div>${esc(m.content)}</div>`;
      }).join('');
      const ctxNote = item.context_total > item.context_shown
        ? ` (últimos ${item.context_shown} de ${item.context_total})`
        : '';
      const correction = item.correction
        ? `<div class="section-title" style="margin-top:1rem">Corrección</div><div class="correction">${esc(item.correction)}</div>`
        : '';
      root.innerHTML = `
        <div class="card">
          <div class="meta">
            <span>#<b>${item.id}</b></span>
            <span>user <b>${esc(item.username) || '—'}</b></span>
            <span>topic <b>${esc(item.topic) || '—'}</b></span>
            <span>status <b>${esc(item.status) || '—'}</b></span>
            <span>rating <b>${esc(item.rating) || '—'}</b></span>
            <span>conf <b>${item.confidence ?? '—'}</b></span>
          </div>
          <div class="section-title">Contexto${esc(ctxNote)}</div>
          <div class="messages">${msgs || '<div class="msg"><div class="role">—</div>(sin contexto)</div>'}</div>
          <div class="section-title">Respuesta a guardar</div>
          <div class="response">${esc(item.bot_response) || '(vacía)'}</div>
          ${correction}
          <div class="actions">
            <button class="discard" id="btn-discard" type="button">Descartar · borra</button>
            <button class="approve" id="btn-approve" type="button">Aprobar · se queda</button>
          </div>
          <div class="hint"><kbd>A</kbd> aprobar · <kbd>D</kbd> descartar · no hace falta mouse</div>
        </div>
      `;
      document.getElementById('btn-approve').onclick = () => act('approve');
      document.getElementById('btn-discard').onclick = () => act('discard');
      renderStats(stats);
    }

    async function loadNext() {
      busy = true;
      try {
        const res = await fetch('/api/next');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al cargar');
        renderStats(data.stats);
        if (!data.item) renderEmpty(data.stats);
        else renderCard(data.item, data.stats);
      } catch (err) {
        root.className = 'error';
        root.textContent = String(err.message || err);
      } finally {
        busy = false;
      }
    }

    async function act(decision) {
      if (busy || !current) return;
      busy = true;
      const approveBtn = document.getElementById('btn-approve');
      const discardBtn = document.getElementById('btn-discard');
      if (approveBtn) approveBtn.disabled = true;
      if (discardBtn) discardBtn.disabled = true;
      try {
        const res = await fetch('/api/decision', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: current.id, decision }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Error al guardar');
        renderStats(data.stats);
        if (!data.item) renderEmpty(data.stats);
        else renderCard(data.item, data.stats);
      } catch (err) {
        root.className = 'error';
        root.textContent = String(err.message || err);
      } finally {
        busy = false;
      }
    }

    document.addEventListener('keydown', (e) => {
      if (busy) return;
      if (e.target && ['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;
      const k = e.key.toLowerCase();
      if (k === 'a' || k === 'arrowright') {
        e.preventDefault();
        act('approve');
      } else if (k === 'd' || k === 'arrowleft' || k === 'backspace') {
        e.preventDefault();
        act('discard');
      }
    });

    loadNext();
  </script>
</body>
</html>
"""


class ReviewApp:
    def __init__(self, db_path: Path, progress_path: Path):
        self.db_path = db_path
        self.progress_path = progress_path
        self.progress = load_progress(progress_path)

    def conn(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def stats_payload(self, conn: sqlite3.Connection) -> dict[str, Any]:
        base = get_stats(conn, self.progress["after_id"])
        base["approved"] = self.progress["approved"]
        base["discarded"] = self.progress["discarded"]
        return base

    def next_payload(self) -> dict[str, Any]:
        with self.conn() as conn:
            item = get_next(conn, self.progress["after_id"])
            return {"item": item, "stats": self.stats_payload(conn)}

    def decide(self, example_id: int, decision: str) -> dict[str, Any]:
        decision = (decision or "").strip().lower()
        if decision not in {"approve", "discard"}:
            raise ValueError("decision must be approve or discard")

        with self.conn() as conn:
            # Only allow deciding the current head of the queue.
            head = get_next(conn, self.progress["after_id"])
            if head is None:
                return {"item": None, "stats": self.stats_payload(conn)}
            if int(head["id"]) != int(example_id):
                raise ValueError(
                    f"stale card: expected id {head['id']}, got {example_id}"
                )

            if decision == "approve":
                if not approve_example(conn, example_id):
                    raise ValueError(f"example {example_id} not found")
                self.progress["approved"] += 1
            else:
                if not discard_example(conn, example_id):
                    raise ValueError(f"example {example_id} not found")
                self.progress["discarded"] += 1

            self.progress["after_id"] = int(example_id)
            save_progress(self.progress_path, self.progress)
            item = get_next(conn, self.progress["after_id"])
            return {"item": item, "stats": self.stats_payload(conn)}


def make_handler(app: ReviewApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            # Avoid logging request bodies / example content.
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: dict) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(code, raw, "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                self._send(200, HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/next":
                try:
                    self._json(200, app.next_payload())
                except Exception as exc:  # noqa: BLE001 — surface to UI
                    self._json(500, {"error": str(exc)})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path != "/api/decision":
                self._json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
                example_id = int(data["id"])
                decision = str(data["decision"])
                self._json(200, app.decide(example_id, decision))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review Diana training examples one by one")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to diana_training.db")
    parser.add_argument(
        "--progress",
        type=Path,
        default=DEFAULT_PROGRESS,
        help="Progress JSON path (cursor + counters)",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset review progress (does not restore deleted rows)",
    )
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1

    if args.reset and args.progress.exists():
        args.progress.unlink()
        print(f"Progress reset: {args.progress}")

    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "Refusing non-local host. Training data must stay on localhost.",
            file=sys.stderr,
        )
        return 2

    app = ReviewApp(args.db, args.progress)
    with connect(args.db) as conn:
        stats = app.stats_payload(conn)
    print(
        f"Queue remaining: {stats['remaining']}  |  rows in DB: {stats['total_in_db']}"
    )
    print(f"Open http://{args.host}:{args.port}")
    print("A = approve (keep) · D = discard (delete) · Ctrl+C to stop")

    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
