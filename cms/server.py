#!/usr/bin/env python3
"""Loopback-only admin server for Book Shelf CMS."""
from __future__ import annotations

import argparse
import getpass
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from cms.core import ValidationError, build_site, hash_password, load_books, safe_upload_name, save_books, verify_password

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("BOOKSHELF_CMS_CONFIG", ROOT / ".admin-config.json"))
SESSIONS: dict[str, dict[str, object]] = {}
ATTEMPTS: dict[str, list[float]] = {}
SESSION_TTL = 8 * 60 * 60


def load_config() -> dict[str, str]:
    if not CONFIG.is_file():
        raise RuntimeError("Admin setup is required. Run: python -m cms.server setup")
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if set(data) != {"username", "password_hash"}:
        raise RuntimeError("Invalid admin configuration")
    return data


def setup() -> None:
    print(f"Creating local admin configuration: {CONFIG}")
    username = input("Username: ").strip()
    if not username or len(username) > 80:
        raise SystemExit("Username is required (maximum 80 characters)")
    first = getpass.getpass("Password (minimum 10 characters): ")
    second = getpass.getpass("Confirm password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    payload = {"username": username, "password_hash": hash_password(first)}
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(CONFIG, 0o600)
    print("Setup complete. The password itself was not stored.")


def publish_changes() -> str:
    build_site(ROOT)
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    if branch != "main":
        raise RuntimeError("Publishing is allowed only from the main branch")
    subprocess.run(["git", "add", "-A", "--", "data/books.json", "library/covers", "library/pdfs"], cwd=ROOT, check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if staged.returncode == 0:
        return "ไม่มีการเปลี่ยนแปลงใหม่สำหรับเผยแพร่"
    if staged.returncode != 1:
        raise RuntimeError("Unable to inspect staged changes")
    message = f"Update book shelf {time.strftime('%Y-%m-%d %H:%M')}"
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)
    return "ส่งข้อมูลขึ้น GitHub แล้ว ระบบกำลังสร้างหน้าเว็บ"


class Handler(BaseHTTPRequestHandler):
    server_version = "BookShelfCMS/1.0"

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def _headers(self, status: int, content_type: str, length: int, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _send(self, status: int, body: bytes, content_type: str = "application/json; charset=utf-8", extra: dict[str, str] | None = None) -> None:
        self._headers(status, content_type, len(body), extra)
        self.wfile.write(body)

    def _json(self, status: int, value: object, extra: dict[str, str] | None = None) -> None:
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), extra=extra)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _read(self, limit: int) -> bytes:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValidationError("Invalid content length") from exc
        if size < 0 or size > limit:
            raise ValidationError("Request is too large")
        return self.rfile.read(size)

    def _read_json(self) -> object:
        try:
            return json.loads(self._read(1_000_000))
        except json.JSONDecodeError as exc:
            raise ValidationError("Invalid JSON") from exc

    def _session(self) -> tuple[str, dict[str, object]] | None:
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        morsel = jar.get("bookshelf_session")
        if not morsel:
            return None
        token = morsel.value
        session = SESSIONS.get(token)
        if not session or time.time() - float(str(session["at"])) > SESSION_TTL:
            SESSIONS.pop(token, None)
            return None
        session["at"] = time.time()
        return token, session

    def _require(self, write: bool = False) -> tuple[str, dict[str, object]]:
        found = self._session()
        if not found:
            raise PermissionError("กรุณาเข้าสู่ระบบ")
        if write and not secrets.compare_digest(str(found[1]["csrf"]), self.headers.get("X-CSRF-Token", "")):
            raise PermissionError("คำขอหมดอายุ กรุณาโหลดหน้าใหม่")
        return found

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path in ("/", "/admin", "/admin/"):
                body = (ROOT / "cms" / "admin.html").read_bytes()
                return self._send(200, body, "text/html; charset=utf-8")
            if parsed.path == "/api/session":
                found = self._session()
                return self._json(200, {"authenticated": bool(found), "csrf": found[1]["csrf"] if found else ""})
            if parsed.path == "/api/books":
                self._require()
                return self._json(200, load_books(ROOT))
            if parsed.path.startswith("/preview/"):
                self._require()
                relative = parsed.path.removeprefix("/preview/")
                candidate = (ROOT / relative).resolve()
                allowed = [(ROOT / "library" / "covers").resolve(), (ROOT / "library" / "pdfs").resolve()]
                if not candidate.is_file() or not any(candidate.is_relative_to(parent) for parent in allowed):
                    return self._error(404, "File not found")
                content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                return self._send(200, candidate.read_bytes(), content_type)
            return self._error(404, "Not found")
        except PermissionError as exc:
            self._error(401, str(exc))
        except (ValidationError, RuntimeError) as exc:
            self._error(400, str(exc))
        except Exception as exc:
            self.log_error("Unhandled GET error: %r", exc)
            self._error(500, "เกิดข้อผิดพลาดภายในระบบ")

    def do_PUT(self) -> None:
        try:
            if urlparse(self.path).path != "/api/books":
                return self._error(404, "Not found")
            self._require(write=True)
            books = save_books(ROOT, self._read_json())
            self._json(200, {"ok": True, "count": len(books)})
        except PermissionError as exc:
            self._error(403, str(exc))
        except (ValidationError, RuntimeError) as exc:
            self._error(400, str(exc))
        except Exception as exc:
            self.log_error("PUT failed: %r", exc)
            self._error(500, "บันทึกไม่สำเร็จ")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/login":
                return self._login()
            if parsed.path == "/api/logout":
                found = self._require(write=True)
                SESSIONS.pop(found[0], None)
                return self._json(200, {"ok": True}, {"Set-Cookie": "bookshelf_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
            self._require(write=True)
            if parsed.path == "/api/upload":
                return self._upload(parse_qs(parsed.query))
            if parsed.path == "/api/build":
                count = build_site(ROOT)
                return self._json(200, {"ok": True, "message": f"สร้างเว็บไซต์แล้ว {count} รายการ"})
            if parsed.path == "/api/publish":
                return self._json(200, {"ok": True, "message": publish_changes()})
            return self._error(404, "Not found")
        except PermissionError as exc:
            self._error(403, str(exc))
        except (ValidationError, RuntimeError, subprocess.CalledProcessError) as exc:
            self._error(400, str(exc))
        except Exception as exc:
            self.log_error("POST failed: %r", exc)
            self._error(500, "ดำเนินการไม่สำเร็จ")

    def _login(self) -> None:
        now = time.time()
        recent = [stamp for stamp in ATTEMPTS.get(self.client_address[0], []) if now - stamp < 300]
        if len(recent) >= 8:
            return self._error(429, "ลองใหม่ภายหลัง")
        body = self._read_json()
        if not isinstance(body, dict):
            raise ValidationError("Invalid login")
        config = load_config()
        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        valid_user = secrets.compare_digest(username, config["username"])
        valid_password = verify_password(password, config["password_hash"])
        if not (valid_user and valid_password):
            recent.append(now)
            ATTEMPTS[self.client_address[0]] = recent
            time.sleep(0.25)
            return self._error(401, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
        ATTEMPTS.pop(self.client_address[0], None)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        SESSIONS[token] = {"csrf": csrf, "at": now}
        self._json(200, {"ok": True, "csrf": csrf}, {"Set-Cookie": f"bookshelf_session={token}; Path=/; HttpOnly; SameSite=Strict"})

    def _upload(self, query: dict[str, list[str]]) -> None:
        kind = query.get("kind", [""])[0]
        original = query.get("filename", [""])[0]
        name = safe_upload_name(original, kind)
        limit = 50 * 1024 * 1024 if kind == "pdf" else 8 * 1024 * 1024
        content = self._read(limit)
        extension = Path(name).suffix
        if kind == "pdf" and not content.startswith(b"%PDF-"):
            raise ValidationError("ไฟล์ไม่ใช่ PDF ที่ถูกต้อง")
        if kind == "cover":
            signatures = {
                ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
                ".jpg": content.startswith(b"\xff\xd8\xff"),
                ".jpeg": content.startswith(b"\xff\xd8\xff"),
                ".gif": content.startswith((b"GIF87a", b"GIF89a")),
                ".webp": len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
            }
            if not signatures.get(extension, False):
                raise ValidationError("ชนิดข้อมูลรูปปกไม่ตรงกับนามสกุล")
        folder = ROOT / "library" / ("pdfs" if kind == "pdf" else "covers")
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / name
        destination.write_bytes(content)
        relative = destination.relative_to(ROOT).as_posix()
        self._json(201, {"ok": True, "path": relative, "preview": "/preview/" + quote(relative)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Local-only Book Shelf CMS")
    parser.add_argument("command", nargs="?", choices=["serve", "setup"], default="serve")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "setup":
        setup()
        return
    load_config()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Book Shelf CMS: http://127.0.0.1:{args.port}/admin/")
    print("Press Ctrl+C to stop. The server listens on this computer only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
