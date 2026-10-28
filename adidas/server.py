#!/usr/bin/env python3
"""adidas Graph KB portal server — medical-style hub with auth + write overlay.

Writes ONLY under adidas KB_ROOT (_uploads / _proposals / _accepted / _meta).
Never writes SOURCE_KB_ROOT.
"""

from __future__ import annotations

try:
    import cgi  # type: ignore
except ImportError:  # Python 3.13+
    cgi = None  # type: ignore
import email
import email.policy
import hashlib
import http.cookies
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    ALL_CONTENT_DIRS,
    KB_ROOT,
    PRODUCT_DIRS,
    SOURCE_KB_ROOT,
    assert_writable_under_kb,
    cfg,
    load_env,
)
import graph_recall as gr  # noqa: E402
import local_wiki_search as wiki_search  # noqa: E402
import overlay  # noqa: E402
import question_rewrite as qr  # noqa: E402
from query import SYSTEM_PROMPT, ask as ask_blocking  # noqa: E402

PORT = int(getattr(getattr(cfg, "server", None), "port", 8780) or 8780)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

_ENV = load_env()
_PORTAL_PASSWORD = _ENV.get("PORTAL_PASSWORD", "")
if not _PORTAL_PASSWORD:
    raise RuntimeError("PORTAL_PASSWORD must be set in ~/.hermes/.env")
_AUTH_COOKIE_NAME = getattr(cfg.server, "cookie_name", "llm_wiki_graph_adidas_auth")
_AUTH_COOKIE_SECRET = _ENV.get("PORTAL_COOKIE_SECRET", "")
if not _AUTH_COOKIE_SECRET:
    print("[auth] WARNING: PORTAL_COOKIE_SECRET not set — deriving from password")
    _AUTH_COOKIE_SECRET = hashlib.sha256(
        ("kb-hub-portal-" + _PORTAL_PASSWORD).encode()
    ).hexdigest()

_LOGIN_ATTEMPTS: dict = {}
_LOGIN_LOCKOUT: dict = {}
_LOGIN_LOCK = threading.Lock()
_QA_TIMESTAMPS: list[float] = []
_QA_LOCK = threading.Lock()
QA_RATE_LIMIT = int(getattr(cfg.server, "qa_rate_limit_per_minute", 10) or 10)

overlay.ensure_dirs()
UPLOADS = overlay.UPLOADS_DIR
HISTORY = os.path.join(KB_ROOT, ".upload-history.json")
QUEUE = os.path.join(KB_ROOT, ".ingest-queue.json")
STATUS = os.path.join(KB_ROOT, ".ingest-status.json")
INGEST_LOCK_FILE = os.path.join(KB_ROOT, ".ingest-lock.json")
state = {"phase": "idle", "message": "", "files": [], "started": None, "done": None}
_state_lock = threading.Lock()


def _api_key() -> str:
    return os.environ.get("DEEPSEEK_API_KEY") or _ENV.get("DEEPSEEK_API_KEY", "") or ""


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def _save(path, data):
    path = assert_writable_under_kb(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_history(entry: dict):
    hist = _load(HISTORY, [])
    hist.insert(0, entry)
    _save(HISTORY, hist[:200])


def _update_history_status(name: str, status: str, **extra):
    hist = _load(HISTORY, [])
    for h in hist:
        if h.get("name") == name:
            h["status"] = status
            h.update(extra)
            break
    _save(HISTORY, hist)


def get_state() -> dict:
    with _state_lock:
        st = dict(state)
    disk = _load(STATUS, {})
    if disk:
        st.update(disk)
    return st


def _public_config() -> dict:
    categories = []
    for c in cfg.categories:
        cat = {
            "id": c.id,
            "name": c.name,
            "color": c.color,
            "dir": c.dir,
            "role": getattr(c, "role", None),
        }
        subs = []
        for sub in getattr(c, "subcategories", []) or []:
            sc = {"name": sub.name, "dir": sub.dir}
            if hasattr(sub, "children") and sub.children:
                sc["children"] = [{"name": ch.name, "dir": ch.dir} for ch in sub.children]
            subs.append(sc)
        if subs:
            cat["subcategories"] = subs
        categories.append(cat)
    theme = cfg.theme.__dict__ if hasattr(cfg.theme, "__dict__") else dict(cfg.theme)
    modes = []
    for m in getattr(cfg.upload, "modes", []) or []:
        modes.append({"id": m.id, "label": m.label, "description": m.description})
    return {
        "brand": {
            "name": cfg.brand.name,
            "public_name": cfg.brand.public_name,
            "display_name": cfg.brand.display_name,
        },
        "categories": categories,
        "theme": theme,
        "server": {"port": PORT},
        "upload": {"modes": modes},
    }


def _kb_tree() -> list:
    root = Path(SOURCE_KB_ROOT)
    tree = []
    for d in ALL_CONTENT_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        children = []
        try:
            entries = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            continue
        for p in entries[:80]:
            if p.name.startswith(".") or p.name == "index.md":
                continue
            if p.is_dir():
                kids = []
                try:
                    for md in sorted(p.rglob("*.md"))[:40]:
                        if md.name == "index.md":
                            continue
                        rel = str(md.relative_to(root).with_suffix("")).replace("\\", "/")
                        kids.append({"name": md.stem, "path": rel})
                except OSError:
                    pass
                children.append({"name": p.name, "path": f"{d}/{p.name}", "children": kids})
            elif p.suffix == ".md":
                rel = str(p.relative_to(root).with_suffix("")).replace("\\", "/")
                children.append({"name": p.stem, "path": rel})
        tree.append({"name": d, "path": d, "children": children})
    # Overlay branch
    accepted = overlay.list_accepted_slugs()
    if accepted:
        kids = [{"name": s.split("/")[-1], "path": s} for s in sorted(accepted)[:200]]
        tree.insert(0, {"name": "_accepted (副本覆盖层)", "path": "_accepted", "children": kids})
    return tree


def _read_page_api(slug: str) -> dict:
    slug = unquote(slug).strip().lstrip("/")
    text = overlay.read_page(slug)
    if not text:
        return {"ok": False, "error": "not found", "slug": slug}
    return {"ok": True, "slug": slug, "content": text[:50000], "overlay": os.path.isfile(overlay.accepted_path(slug))}


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content + ("\n" if not content.endswith("\n") else "")


def _create_proposal_from_file(fpath: str, mode: str) -> dict:
    """Create a review proposal for an uploaded file (MVP: md/txt auto, others stub)."""
    fname = os.path.basename(fpath)
    stem = os.path.splitext(fname)[0]
    ext = os.path.splitext(fname)[1].lower()
    slug = f"轻运动产品/待分类/{stem}"
    title = stem
    if ext in (".md", ".txt"):
        raw = Path(fpath).read_text(encoding="utf-8", errors="ignore")
        if raw.lstrip().startswith("---"):
            proposed = _strip_fences(raw)
        else:
            proposed = f"---\ntitle: \"{title}\"\ntype: 配件\nsource: upload\n---\n\n{raw.strip()}\n"
    else:
        proposed = (
            f"---\ntitle: \"{title}\"\ntype: 配件\nsource: upload\nattachment: {fname}\n---\n\n"
            f"# {title}\n\n上传附件：`_uploads/{fname}`（二进制未自动解析）。\n"
            f"请人工补充正文后批准，或改写本提案。\n"
        )
    proposal = {
        "title": title,
        "slug": slug,
        "source": "upload",
        "action": "create",
        "status": "pending",
        "mode": mode,
        "proposed_content": proposed,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "attachment": fname if ext not in (".md", ".txt") else "",
    }
    safe = slug.replace("/", "_")
    path = os.path.join(overlay.PROPOSALS_DIR, f"{safe}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proposal, f, ensure_ascii=False, indent=2)
    return proposal


def _process_queue_async():
    """Background: turn queued uploads into proposals / direct overlay writes."""
    with _state_lock:
        state.update({"phase": "processing", "message": "处理上传队列…", "started": time.time()})
    _save(STATUS, {"phase": "processing", "message": "处理上传队列…"})
    try:
        q = _load(QUEUE, {"files": [], "mode": "review"})
        if isinstance(q, list):
            q = {"files": q, "mode": "review"}
        mode = q.get("mode") or "review"
        files = q.get("files") or []
        for item in files:
            name = item["name"] if isinstance(item, dict) else item
            fpath = os.path.join(UPLOADS, name)
            if not os.path.isfile(fpath):
                _update_history_status(name, "error", error="file missing")
                continue
            try:
                prop = _create_proposal_from_file(fpath, mode)
                if mode == "direct":
                    overlay.write_accepted(prop["slug"], prop["proposed_content"])
                    prop["status"] = "approved"
                    prop["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    safe = prop["slug"].replace("/", "_")
                    with open(os.path.join(overlay.PROPOSALS_DIR, f"{safe}.json"), "w", encoding="utf-8") as f:
                        json.dump(prop, f, ensure_ascii=False, indent=2)
                    _update_history_status(name, "ingested", slug=prop["slug"])
                else:
                    _update_history_status(name, "proposal", slug=prop["slug"])
                # archive original
                arch = os.path.join(UPLOADS, "_archived", name)
                shutil.move(fpath, arch)
            except Exception as exc:  # noqa: BLE001
                _update_history_status(name, "error", error=str(exc))
        _save(QUEUE, {"files": [], "mode": mode})
        try:
            wiki_search.rebuild_corpus(force=True)
        except Exception:  # noqa: BLE001
            pass
        msg = "上传处理完成"
        with _state_lock:
            state.update({"phase": "done", "message": msg, "done": time.time()})
        _save(STATUS, {"phase": "done", "message": msg})
    except Exception as exc:  # noqa: BLE001
        with _state_lock:
            state.update({"phase": "error", "message": str(exc)})
        _save(STATUS, {"phase": "error", "message": str(exc)})


def _trigger_ingest():
    threading.Thread(target=_process_queue_async, daemon=True).start()


def _parse_multipart(rfile, content_type: str, length: int) -> list[tuple[str, bytes]]:
    """Return list of (filename, raw_bytes). Works without cgi on 3.13+."""
    raw = rfile.read(length)
    # Prefer cgi if available
    if cgi is not None:
        try:
            import io

            environ = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            }
            form = cgi.FieldStorage(
                fp=io.BytesIO(raw),
                headers={"content-type": content_type, "content-length": str(length)},
                environ=environ,
            )
            out = []
            keys = form.keys() if hasattr(form, "keys") else []
            for key in keys:
                item = form[key]
                items = item if isinstance(item, list) else [item]
                for it in items:
                    if getattr(it, "filename", None):
                        out.append((os.path.basename(it.filename), it.file.read()))
            if out:
                return out
        except Exception:  # noqa: BLE001
            pass

    # email fallback
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
    msg = email.message_from_bytes(header + raw, policy=email.policy.default)
    out = []
    for part in msg.walk():
        if part.get_content_disposition() != "form-data":
            continue
        fname = part.get_filename()
        if not fname:
            continue
        payload = part.get_payload(decode=True) or b""
        out.append((os.path.basename(fname), payload))
    return out


# (removed duplicate _parse_multipart body above)


TASKS = [
    {
        "id": "rebuild",
        "name": "🔄 重建关系索引+灌图",
        "desc": "render 关系索引 → extract → Neo4j load_data（不写源 KB）",
    },
    {
        "id": "validate",
        "name": "✅ 轻量一致性检查",
        "desc": "只读扫描源 KB + overlay，报告写入 _meta/_issues.md",
    },
    {
        "id": "fts-rebuild",
        "name": "🔍 重建全文索引",
        "desc": "刷新本地 jieba 语料（含 _accepted overlay）",
    },
]


class ThreadingHTTPServer(ThreadingMixIn, __import__("http.server", fromlist=["HTTPServer"]).HTTPServer):
    daemon_threads = True


class Handler(SimpleHTTPRequestHandler):
    _LOGIN_PAGE = ""
    _PORTAL_PAGE = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("[server] " + (fmt % args) + "\n")

    def _json(self, payload, code: int = 200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _check_auth(self) -> bool:
        cookie_str = self.headers.get("Cookie", "")
        if not cookie_str:
            return False
        try:
            c = http.cookies.SimpleCookie()
            c.load(cookie_str)
            token = c.get(_AUTH_COOKIE_NAME)
            return bool(token and token.value == _AUTH_COOKIE_SECRET)
        except Exception:  # noqa: BLE001
            return False

    def _set_auth_cookie(self):
        c = http.cookies.SimpleCookie()
        c[_AUTH_COOKIE_NAME] = _AUTH_COOKIE_SECRET
        c[_AUTH_COOKIE_NAME]["path"] = "/"
        c[_AUTH_COOKIE_NAME]["httponly"] = True
        days = int(getattr(cfg.server, "cookie_days", 30) or 30)
        c[_AUTH_COOKIE_NAME]["max-age"] = 86400 * days
        self.send_header("Set-Cookie", c.output(header="", sep=""))

    def _serve_html(self, html: str, code: int = 200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_qa_rate(self) -> bool:
        if QA_RATE_LIMIT <= 0:
            return False
        now = time.time()
        with _QA_LOCK:
            global _QA_TIMESTAMPS
            _QA_TIMESTAMPS = [t for t in _QA_TIMESTAMPS if now - t < 60]
            if len(_QA_TIMESTAMPS) >= QA_RATE_LIMIT:
                self._json({"ok": False, "error": "问答过于频繁，请稍后再试"}, 429)
                return True
            _QA_TIMESTAMPS.append(now)
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/login"):
            self._serve_html(Handler._LOGIN_PAGE)
            return
        if path == "/portal":
            if not self._check_auth():
                self._serve_html(Handler._LOGIN_PAGE)
                return
            self._serve_html(Handler._PORTAL_PAGE)
            return
        if path == "/logout":
            c = http.cookies.SimpleCookie()
            c[_AUTH_COOKIE_NAME] = ""
            c[_AUTH_COOKIE_NAME]["path"] = "/"
            c[_AUTH_COOKIE_NAME]["max-age"] = 0
            self.send_response(302)
            self.send_header("Set-Cookie", c.output(header="", sep=""))
            self.send_header("Location", "/login")
            self.end_headers()
            return

        # Public APIs
        if path == "/health":
            self._json({"ok": True, "service": "adidas-graph", "port": PORT})
            return
        if path == "/status":
            self._json(get_state())
            return
        if path == "/api/config":
            self._json(_public_config())
            return
        if path == "/api/kb-tree":
            self._json(_kb_tree())
            return
        if path == "/graph/stats":
            try:
                self._json({"ok": True, **gr.graph_stats()})
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 503)
            return

        # Auth-gated
        if path.startswith("/api/") or path in ("/history", "/queue") or path.endswith(".html"):
            if not self._check_auth() and path not in ("/api/config", "/api/kb-tree"):
                if path.endswith(".html"):
                    self.send_response(302)
                    self.send_header("Location", "/login")
                    self.end_headers()
                    return
                self._json({"error": "authentication required"}, 401)
                return

        if path.startswith("/api/page"):
            slug = (parse_qs(parsed.query).get("slug") or [""])[0]
            self._json(_read_page_api(slug))
            return
        if path == "/api/proposals":
            self.handle_proposals()
            return
        if path == "/api/tasks":
            pending = 0
            if os.path.isdir(overlay.PROPOSALS_DIR):
                for fn in os.listdir(overlay.PROPOSALS_DIR):
                    if not fn.endswith(".json"):
                        continue
                    try:
                        d = json.loads(Path(overlay.PROPOSALS_DIR, fn).read_text(encoding="utf-8"))
                        if d.get("status") == "pending":
                            pending += 1
                    except Exception:  # noqa: BLE001
                        pass
            self._json({"tasks": TASKS, "pending_proposals": pending})
            return
        if path == "/api/issues":
            p = os.path.join(overlay.META_DIR, "_issues.md")
            if os.path.isfile(p):
                self._json({"ok": True, "content": Path(p).read_text(encoding="utf-8")})
            else:
                self._json({"ok": True, "content": "（尚无检查报告，请在自检计划中运行 validate）"})
            return
        if path == "/history":
            self._json({"history": _load(HISTORY, [])})
            return
        if path == "/queue":
            self._json({"queue": _load(QUEUE, {"files": [], "mode": "review"})})
            return

        if path.endswith((".html", ".js", ".css", ".json", ".svg", ".png", ".ico", ".md")):
            return super().do_GET()
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path.split("?")[0]

        if path == "/login":
            self.handle_login()
            return

        # Public Q&A (rate-limited)
        if path in ("/ask", "/ask-stream", "/ask-deep", "/ask-rewrite"):
            if self._check_qa_rate():
                return
            if path == "/ask-rewrite":
                self.handle_ask_rewrite()
                return
            if path in ("/ask-stream", "/ask-deep"):
                self.handle_ask_stream(deep=(path == "/ask-deep"))
                return
            body = self._read_json()
            q = (body.get("question") or "").strip()
            if not q:
                self._json({"ok": False, "error": "question required"}, 400)
                return
            self._json({"ok": True, **ask_blocking(q, use_llm=bool(body.get("use_llm", True)), skip_rewrite=bool(body.get("skip_rewrite")))})
            return

        if not self._check_auth():
            self._json({"error": "authentication required"}, 401)
            return

        if path.startswith("/upload"):
            self.handle_upload()
            return
        if path == "/history/clear":
            _save(HISTORY, [])
            self._json({"ok": True})
            return
        if path in ("/api/proposals/approve", "/api/proposals/reject"):
            self.handle_proposal_action(approve=path.endswith("/approve"))
            return
        if path == "/api/tasks/run":
            self.handle_tasks_run()
            return
        if path == "/api/save":
            self.handle_save()
            return

        self._json({"ok": False, "error": "not found"}, 404)

    def handle_login(self):
        client_ip = self.client_address[0]
        now = time.time()
        with _LOGIN_LOCK:
            lockout_until = _LOGIN_LOCKOUT.get(client_ip, 0)
            if lockout_until > now:
                remaining = int(lockout_until - now)
                self._json({"ok": False, "error": f"登录尝试过多，请 {remaining} 秒后再试", "retry_after_seconds": remaining}, 429)
                return
            attempts = [t for t in _LOGIN_ATTEMPTS.get(client_ip, []) if t > now - 60]
            _LOGIN_ATTEMPTS[client_ip] = attempts

        body = self._read_json()
        pwd = body.get("password", "")
        if pwd == _PORTAL_PASSWORD:
            with _LOGIN_LOCK:
                _LOGIN_ATTEMPTS.pop(client_ip, None)
                _LOGIN_LOCKOUT.pop(client_ip, None)
            self.send_response(200)
            self._set_auth_cookie()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        with _LOGIN_LOCK:
            attempts = [t for t in _LOGIN_ATTEMPTS.get(client_ip, []) if t > now - 60]
            attempts.append(now)
            _LOGIN_ATTEMPTS[client_ip] = attempts
            remaining = max(0, 5 - len(attempts))
            if len(attempts) >= 10:
                _LOGIN_LOCKOUT[client_ip] = now + 900
                self._json({"ok": False, "error": "登录尝试过多，已锁定 15 分钟", "retry_after_seconds": 900}, 429)
                return
        self._json({"ok": False, "error": f"密码错误（还剩 {remaining} 次尝试）" if remaining <= 2 else "密码错误"}, 401)

    def handle_upload(self):
        ct = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ct:
            self._json({"ok": False, "error": "multipart required"}, 400)
            return
        params = parse_qs(urlparse(self.path).query)
        mode = (params.get("mode") or ["review"])[0]
        if mode not in ("review", "direct"):
            mode = "review"
        length = int(self.headers.get("Content-Length") or 0)
        files = _parse_multipart(self.rfile, ct, length)
        allowed = {".pdf", ".docx", ".xlsx", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".pptx", ".ppt"}
        saved, rejected = [], []
        for fname, blob in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in allowed:
                rejected.append(fname)
                continue
            dest = assert_writable_under_kb(os.path.join(UPLOADS, fname))
            c = 1
            while os.path.exists(dest):
                n, e = os.path.splitext(fname)
                dest = assert_writable_under_kb(os.path.join(UPLOADS, f"{n}-{c}{e}"))
                c += 1
            with open(dest, "wb") as f:
                f.write(blob)
            entry = {
                "name": os.path.basename(dest),
                "original": fname,
                "size": len(blob),
                "status": "queued",
                "mode": mode,
                "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            add_history(entry)
            saved.append(entry)
        if saved:
            _save(QUEUE, {"files": [{"name": s["name"]} for s in saved], "mode": mode})
            _save(STATUS, {"phase": "queued", "message": f"{len(saved)} 个文件等待处理…"})
            _trigger_ingest()
        self._json({"ok": True, "files": saved, "rejected": rejected, "mode": mode})

    def handle_proposals(self):
        props = []
        if os.path.isdir(overlay.PROPOSALS_DIR):
            for fn in sorted(os.listdir(overlay.PROPOSALS_DIR)):
                if fn.endswith(".json"):
                    try:
                        props.append(json.loads(Path(overlay.PROPOSALS_DIR, fn).read_text(encoding="utf-8")))
                    except Exception:  # noqa: BLE001
                        pass
        self._json(props)

    def handle_proposal_action(self, approve: bool):
        body = self._read_json()
        slug = body.get("slug", "")
        safe = slug.replace("/", "_")
        prop_path = os.path.join(overlay.PROPOSALS_DIR, f"{safe}.json")
        if not os.path.isfile(prop_path):
            self._json({"ok": False, "error": "proposal not found"})
            return
        proposal = json.loads(Path(prop_path).read_text(encoding="utf-8"))
        if approve:
            try:
                content = _strip_fences(proposal.get("proposed_content") or "")
                if not content.strip():
                    self._json({"ok": False, "error": "empty proposed_content"})
                    return
                # Write to overlay only — never SOURCE_KB_ROOT
                overlay.write_accepted(slug, content)
                proposal["status"] = "approved"
                proposal["approved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                proposal["written_to"] = f"_accepted/{slug}.md"
                wiki_search.rebuild_corpus(force=True)
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": str(exc)})
                return
        else:
            proposal["status"] = "rejected"
            proposal["rejected_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if body.get("reason"):
                proposal["reject_reason"] = body["reason"]
        Path(prop_path).write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
        # append log
        log_path = os.path.join(KB_ROOT, "log.md")
        today = time.strftime("%Y-%m-%d")
        action = "approved" if approve else "rejected"
        entry = f"\n- [{action}] {today} {slug}"
        if os.path.exists(log_path):
            lt = Path(log_path).read_text(encoding="utf-8")
            if f"## {today}" in lt:
                lt = lt.replace(f"## {today}", f"## {today}{entry}")
            else:
                lt += f"\n## {today}{entry}\n"
        else:
            lt = f"# 操作日志\n\n## {today}{entry}\n"
        Path(log_path).write_text(lt, encoding="utf-8")
        self._json({"ok": True, "status": proposal["status"]})

    def handle_save(self):
        """Save edited page into overlay (never source)."""
        body = self._read_json()
        slug = (body.get("slug") or "").strip()
        content = body.get("content") or ""
        if not slug or not content:
            self._json({"ok": False, "error": "slug/content required"}, 400)
            return
        try:
            path = overlay.write_accepted(slug, content)
            wiki_search.rebuild_corpus(force=True)
            self._json({"ok": True, "path": path})
        except Exception as exc:  # noqa: BLE001
            self._json({"ok": False, "error": str(exc)})

    def handle_tasks_run(self):
        body = self._read_json()
        task_id = body.get("task") or ""
        if task_id == "rebuild":
            def _run():
                try:
                    r = subprocess.run(
                        [sys.executable, str(ROOT / "graph" / "load_data.py")],
                        cwd=str(ROOT),
                        capture_output=True,
                        text=True,
                        timeout=600,
                    )
                    Path(overlay.META_DIR, "last_rebuild.log").write_text(
                        (r.stdout or "") + "\n" + (r.stderr or ""), encoding="utf-8"
                    )
                except Exception as exc:  # noqa: BLE001
                    Path(overlay.META_DIR, "last_rebuild.log").write_text(str(exc), encoding="utf-8")

            threading.Thread(target=_run, daemon=True).start()
            self._json({"ok": True, "message": "已启动灌图，详见 _meta/last_rebuild.log"})
            return
        if task_id == "validate":
            issues = []
            root = Path(SOURCE_KB_ROOT)
            # sample: missing type frontmatter in a few product dirs
            for d in PRODUCT_DIRS:
                base = root / d
                if not base.is_dir():
                    issues.append(f"- 缺少品类目录: {d}")
                    continue
            # stem collisions note
            issues.append("- Product `name` 唯一约束：跨品类同 stem 会合并（见 SCHEMA.md）")
            issues.append(f"- overlay 页数: {len(overlay.list_accepted_slugs())}")
            pending_n = 0
            for f in Path(overlay.PROPOSALS_DIR).glob("*.json"):
                try:
                    if json.loads(f.read_text(encoding="utf-8")).get("status") == "pending":
                        pending_n += 1
                except Exception:  # noqa: BLE001
                    pass
            issues.append(f"- 待审提案: {pending_n}")
            text = "# adidas 一致性检查\n\n" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n" + "\n".join(issues) + "\n"
            Path(overlay.META_DIR, "_issues.md").write_text(text, encoding="utf-8")
            self._json({"ok": True, "message": "已写入 _meta/_issues.md"})
            return
        if task_id == "fts-rebuild":
            n = wiki_search.rebuild_corpus(force=True)
            self._json({"ok": True, "message": f"全文索引重建完成: {n} pages"})
            return
        self._json({"ok": False, "error": f"unknown task: {task_id}"}, 400)

    def handle_ask_rewrite(self):
        body = self._read_json()
        result = qr.rewrite_question(
            body.get("question", ""),
            lang=body.get("lang", "zh"),
            feedback=body.get("feedback", ""),
            previous_rewrite=body.get("previous_rewrite", ""),
            api_key=_api_key(),
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
        )
        self._json(qr.to_api_dict(result))

    def handle_ask_stream(self, deep: bool = False):
        body = self._read_json()
        question = (body.get("question") or "").strip()
        lang = body.get("lang", "zh")
        rewrite_meta = body.get("rewrite_meta") or {}
        if not question:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":"missing question"}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def sse(event: str, data: dict):
            msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            try:
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                raise

        try:
            if rewrite_meta.get("intent_hint"):
                sse("step", {"id": 0, "type": "planning", "action": "✏️",
                             "detail": f"改写意图: {rewrite_meta.get('intent_hint')}",
                             "rewrite_meta": rewrite_meta})

            sse("step", {"id": 1, "type": "searching", "action": "🕸",
                         "detail": f"图谱优先召回: {question}"})
            result = gr.recall(question)
            context_parts: list[str] = []
            seen: set[str] = set()

            if result.hit:
                sse("step", {"id": 1, "type": "searching", "action": "🕸",
                             "detail": f"图谱模板: {result.template_id}",
                             "graph_template": result.template_id})
                if result.facts_text:
                    context_parts.append(result.facts_text)
                if result.template_id == "series_family_listing":
                    # Load ALL family series pages (answers come from 系列/*)
                    page_budget = list(result.source_slugs)
                else:
                    prefer = [s for s in result.source_slugs if s.startswith(("科技/", "系列/"))]
                    products = [s for s in result.source_slugs if s not in prefer]
                    page_budget = prefer[:4] + products[:6]
                for s in page_budget:
                    if s in seen:
                        continue
                    body_text = gr.load_source_page(s)
                    if not body_text:
                        continue
                    seen.add(s)
                    context_parts.append(f"## {s}\n{body_text}")
                    sse("step", {"id": len(seen) + 1, "type": "reading", "action": "📖",
                                 "detail": f"读取 {s}"})

            if (not result.hit) or (not result.rows) or deep:
                sse("step", {"id": 2, "type": "searching", "action": "🔍",
                             "detail": f"本地 Wiki 检索: {question}"})
                for h in wiki_search.search(question, limit=8 if deep else 5):
                    slug = h.get("slug") or ""
                    if not slug or slug in seen:
                        continue
                    seen.add(slug)
                    body_text = wiki_search.get(slug) or gr.load_source_page(slug)
                    if body_text:
                        context_parts.append(f"## {slug}\n{body_text[:6000]}")
                        sse("step", {"id": len(seen) + 1, "type": "reading", "action": "📖",
                                     "detail": f"读取 {slug}"})

            context = "\n\n---\n\n".join(context_parts) if context_parts else "(未找到相关内容)"
            key = _api_key()
            if not key:
                lines = []
                if result.hit:
                    lines.append(result.facts_text)
                    lines.append(f"\n模板: `{result.template_id}`")
                if seen:
                    lines.append("\n来源页:\n" + "\n".join(f"- `{s}`" for s in list(seen)[:12]))
                if not lines:
                    lines.append("未命中图谱/全文检索。" if lang == "zh" else "No hits.")
                lines.append("\n\n_(未配置 DEEPSEEK_API_KEY)_")
                sse("answer", {"answer": "\n".join(lines)})
                sse("done", {})
                return

            sse("step", {"id": 99, "type": "thinking", "action": "🤔", "detail": "AI 综合分析中..."})
            import requests

            sys_content = SYSTEM_PROMPT if lang == "zh" else (
                "You are an adidas product KB assistant. Answer ONLY from context."
            )
            user_content = (
                f"=== 知识库内容 ===\n{context[:24000]}\n=== 内容结束 ===\n\n问题：{question}"
                if lang == "zh"
                else f"=== KB ===\n{context[:24000]}\n=== End ===\n\nQuestion: {question}"
            )
            resp = requests.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": sys_content},
                        {"role": "user", "content": user_content},
                    ],
                    "stream": True,
                    "temperature": 0.45,
                    "max_tokens": int(getattr(cfg.server.qa, "max_tokens", 2500) or 2500),
                },
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                stream=True,
                timeout=120,
            )
            resp.raise_for_status()
            total: list[str] = []
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    content = chunk.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                    if content:
                        total.append(content)
                        sse("token", {"token": content})
                except json.JSONDecodeError:
                    continue
            answer = "".join(total).strip()
            if answer:
                sse("answer", {"answer": answer})
            else:
                sse("error", {"message": "空回答"})
            sse("done", {})
        except Exception as exc:  # noqa: BLE001
            try:
                sse("error", {"message": str(exc)})
                sse("done", {})
            except Exception:  # noqa: BLE001
                pass


def _build_login_pages():
    brand = cfg.brand.public_name
    Handler._LOGIN_PAGE = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{brand}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,system-ui,sans-serif;background:#0a0a0a;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}}
.login-box{{background:#141414;border:1px solid #2a2a2a;border-radius:12px;padding:48px;width:360px;max-width:90vw;text-align:center}}
.login-box h1{{font-size:20px;font-weight:600;margin-bottom:8px}}
.login-box .subtitle{{font-size:13px;color:#888;margin-bottom:32px}}
.login-box input{{width:100%;padding:12px 16px;background:#1a1a1a;border:1px solid #333;border-radius:8px;color:#fff;font-size:15px;outline:none}}
.login-box button{{width:100%;padding:12px;margin-top:16px;background:#fff;color:#000;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer}}
.login-box .error{{color:#ff5555;font-size:13px;margin-top:12px;display:none}}
</style></head><body>
<div class="login-box">
<h1>{brand}</h1>
<p class="subtitle">请输入访问密码</p>
<form id="f"><input type="password" id="pwd" placeholder="密码" autofocus><button type="submit">进入</button></form>
<p class="error" id="err">密码错误，请重试</p>
</div>
<script>
document.getElementById('f').addEventListener('submit',async e=>{{e.preventDefault()
const r=await fetch('/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{password:document.getElementById('pwd').value}})}})
r.ok?window.location.href='/portal':(document.getElementById('err').style.display='block',document.getElementById('pwd').value='')}})
</script></body></html>"""

    Handler._PORTAL_PAGE = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{brand}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,system-ui,sans-serif;background:#0a0a0a;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}}
.portal{{text-align:center;max-width:520px;width:90vw}}
.portal h1{{font-size:22px;font-weight:600;margin-bottom:4px}}
.portal .subtitle{{font-size:13px;color:#666;margin-bottom:36px}}
.cards{{display:flex;gap:16px;justify-content:center;flex-wrap:wrap}}
.card{{background:#141414;border:1px solid #2a2a2a;border-radius:12px;padding:32px 24px;width:200px;text-decoration:none;color:#e0e0e0}}
.card:hover{{border-color:#555}}
.card-icon{{font-size:36px;margin-bottom:12px}}
.card-title{{font-size:16px;font-weight:600;margin-bottom:6px}}
.card-desc{{font-size:12px;color:#666}}
.logout{{margin-top:32px;font-size:12px}}
.logout a{{color:#888;text-decoration:none}}
</style></head><body>
<div class="portal">
<h1>{brand}</h1>
<p class="subtitle">选择要访问的功能</p>
<div class="cards">
<a class="card" href="/product-hub.html"><div class="card-icon">🧠</div><div class="card-title">产品中心</div><div class="card-desc">问答 · 上传 · 审核 · 自检</div></a>
<a class="card" href="http://localhost:7475" target="_blank"><div class="card-icon">🕸</div><div class="card-title">Neo4j Browser</div><div class="card-desc">bolt 7688 · 演示图查询</div></a>
</div>
<p class="logout"><a href="/logout">退出登录</a></p>
</div></body></html>"""


def main():
    _build_login_pages()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[adidas] portal http://127.0.0.1:{PORT}/  (login → /portal → product-hub)", flush=True)
    print(f"  KB_ROOT        = {KB_ROOT}", flush=True)
    print(f"  SOURCE_KB_ROOT = {SOURCE_KB_ROOT}", flush=True)
    print("  writes: _uploads / _proposals / _accepted / _meta  (never SOURCE_KB / medical)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[adidas] stopped", flush=True)


if __name__ == "__main__":
    main()
