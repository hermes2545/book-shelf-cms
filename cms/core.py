"""Core catalogue and build functions for the local-first CMS."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import tempfile
import unicodedata
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any


class ValidationError(ValueError):
    pass


_REQUIRED = ("id", "title", "author", "category", "published_at", "description", "pdf")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_ALLOWED = {"pdf": {".pdf"}, "cover": {".png", ".jpg", ".jpeg", ".webp", ".gif"}}


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValidationError("Password must contain at least 10 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )
    return f"scrypt-v1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        version, salt_hex, digest_hex = encoded.split("$", 2)
        if version != "scrypt-v1":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**15, r=8, p=1, dklen=32,
            maxmem=64 * 1024 * 1024
        )
        return hmac.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def _text(value: Any, field: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    value = unicodedata.normalize("NFC", value).strip()
    if required and not value:
        raise ValidationError(f"{field} is required")
    if len(value) > maximum:
        raise ValidationError(f"{field} is too long")
    return value


def _media_path(value: Any, kind: str, required: bool = True) -> str:
    value = _text(value, kind, 300, required)
    if not value:
        return ""
    path = PurePosixPath(value)
    prefix = "library/pdfs" if kind == "pdf" else "library/covers"
    if path.is_absolute() or ".." in path.parts or str(path.parent) != prefix:
        raise ValidationError(f"{kind} must be a direct file inside {prefix}/")
    if path.suffix.lower() not in _ALLOWED[kind]:
        raise ValidationError(f"unsupported {kind} file type")
    return str(path)


def normalize_book(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError("Book must be an object")
    missing = [field for field in _REQUIRED if field not in raw]
    if missing:
        raise ValidationError("Missing fields: " + ", ".join(missing))
    book_id = _text(raw["id"], "id", 80).lower()
    if not _ID_RE.fullmatch(book_id):
        raise ValidationError("id must contain lowercase letters, numbers, and hyphens")
    published_at = _text(raw["published_at"], "published_at", 10)
    try:
        date.fromisoformat(published_at)
    except ValueError as exc:
        raise ValidationError("published_at must use YYYY-MM-DD") from exc
    published = raw.get("published", False)
    if not isinstance(published, bool):
        raise ValidationError("published must be true or false")
    sort_order = raw.get("sort_order", 0)
    if isinstance(sort_order, bool) or not isinstance(sort_order, int) or not 0 <= sort_order <= 1_000_000:
        raise ValidationError("sort_order must be an integer from 0 to 1000000")
    return {
        "id": book_id,
        "title": _text(raw["title"], "title", 200),
        "author": _text(raw["author"], "author", 160),
        "category": _text(raw["category"], "category", 100),
        "published_at": published_at,
        "description": _text(raw["description"], "description", 2000, False),
        "pdf": _media_path(raw["pdf"], "pdf"),
        "cover": _media_path(raw.get("cover", ""), "cover", False),
        "published": published,
        "sort_order": sort_order,
    }


def normalize_catalog(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValidationError("Catalog must be a list")
    books = [normalize_book(book) for book in raw]
    ids = [book["id"] for book in books]
    if len(ids) != len(set(ids)):
        raise ValidationError("Book IDs must be unique")
    return books


def safe_upload_name(original_name: str, kind: str) -> str:
    if kind not in _ALLOWED:
        raise ValidationError("Unknown upload kind")
    extension = Path(original_name).suffix.lower()
    if extension not in _ALLOWED[kind]:
        raise ValidationError(f"Unsupported {kind} extension")
    return secrets.token_hex(16) + extension


def load_books(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "books.json"
    try:
        return normalize_catalog(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid catalog JSON: {exc}") from exc


def save_books(root: Path, raw: Any) -> list[dict[str, Any]]:
    books = normalize_catalog(raw)
    path = root / "data" / "books.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(books, ensure_ascii=False, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(prefix="books-", suffix=".json", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return books


def _safe_inline_json(value: Any) -> str:
    # Escaping "<" prevents an inline JSON value from ending the script block.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("&", "\\u0026").replace("<", "\\u003c")


def build_site(root: Path) -> int:
    root = root.resolve()
    books = load_books(root)
    published = [book for book in books if book["published"]]
    published.sort(key=lambda book: (book["sort_order"], book["published_at"], book["id"]), reverse=True)
    for book in published:
        for field in ("pdf", "cover"):
            if book[field] and not (root / book[field]).is_file():
                raise ValidationError(f"Missing file for {book['id']}: {book[field]}")

    resource_root = Path(__file__).resolve().parents[1]
    template_root = root if (root / "templates" / "index.html").is_file() else resource_root
    static_root = root if (root / "static").is_dir() else resource_root
    template = (template_root / "templates" / "index.html").read_text(encoding="utf-8")
    viewer_template = (template_root / "templates" / "viewer.html").read_text(encoding="utf-8")
    html = template.replace("{{BOOKS_JSON}}", _safe_inline_json(published))
    dist = root / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    (dist / "assets").mkdir(parents=True)
    for name in ("site.css", "site.js", "viewer.css", "viewer.js"):
        shutil.copy2(static_root / "static" / name, dist / "assets" / name)
    shutil.copytree(static_root / "static" / "sounds", dist / "assets" / "sounds")
    shutil.copytree(static_root / "static" / "vendor", dist / "assets" / "vendor")
    shutil.copy2(static_root / "static" / "favicon.svg", dist / "favicon.svg")
    if (root / "library").exists():
        shutil.copytree(root / "library", dist / "library")
    (dist / "index.html").write_text(html, encoding="utf-8")
    (dist / "viewer.html").write_text(viewer_template, encoding="utf-8")
    (dist / "catalog.json").write_text(json.dumps(published, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (dist / ".nojekyll").write_text("", encoding="utf-8")
    return len(published)
