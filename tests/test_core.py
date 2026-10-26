import json
import subprocess
import stat
import tempfile
import unittest
from pathlib import Path

from cms.core import (
    ValidationError,
    build_site,
    hash_password,
    normalize_book,
    safe_upload_name,
    verify_password,
)
from cms.server import create_admin_config, publish_changes


class PasswordTests(unittest.TestCase):
    def test_first_run_setup_writes_private_hashed_config_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".admin-config.json"
            create_admin_config(path, "reader", "correct horse battery", "correct horse battery")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["username"], "reader")
            self.assertNotIn("password", payload)
            self.assertTrue(verify_password("correct horse battery", payload["password_hash"]))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(ValidationError):
                create_admin_config(path, "other", "another good password", "another good password")

    def test_password_hash_is_salted_and_verifiable(self):
        encoded = hash_password("correct horse battery staple")
        self.assertNotIn("correct horse battery staple", encoded)
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong", encoded))


class CatalogTests(unittest.TestCase):
    def test_publish_retries_push_when_prior_commit_is_unpushed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            root = temp / "work"
            remote = temp / "remote.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "CMS Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "cms-test@example.invalid"], cwd=root, check=True)
            (root / "data").mkdir()
            (root / "library" / "pdfs").mkdir(parents=True)
            (root / "library" / "covers").mkdir(parents=True)
            (root / "data" / "books.json").write_text("[]\n", encoding="utf-8")
            (root / "library" / "pdfs" / ".gitkeep").touch()
            (root / "library" / "covers" / ".gitkeep").touch()
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
            subprocess.run(["git", "push", "-u", "origin", "main"], cwd=root, check=True, capture_output=True)
            (root / "data" / "books.json").write_text("[]\n\n", encoding="utf-8")
            subprocess.run(["git", "add", "data/books.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "Already committed locally"], cwd=root, check=True, capture_output=True)

            publish_changes(root)

            local_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True).stdout.strip()
            remote_head = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "main"], text=True, capture_output=True, check=True).stdout.strip()
            self.assertEqual(local_head, remote_head)

    def test_admin_ui_supports_first_run_password_setup(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "cms" / "admin.html").read_text(encoding="utf-8")
        self.assertIn('id="setup-form"', html)
        self.assertIn("/api/setup", html)

    def test_normalize_book_rejects_paths_outside_library(self):
        with self.assertRaises(ValidationError):
            normalize_book({
                "id": "guide-1",
                "title": "Guide",
                "author": "Author",
                "category": "General",
                "published_at": "2026-08-23",
                "description": "Description",
                "pdf": "../private.pdf",
                "cover": "library/covers/guide.webp",
                "published": True,
                "sort_order": 1,
            })

    def test_safe_upload_name_preserves_only_allowed_extension(self):
        name = safe_upload_name("Quarterly Plan (final).PDF", "pdf")
        self.assertRegex(name, r"^[a-f0-9]{32}\.pdf$")
        with self.assertRaises(ValidationError):
            safe_upload_name("payload.php", "cover")

    def test_build_site_publishes_only_published_books_and_escapes_inline_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "library" / "pdfs").mkdir(parents=True)
            (root / "library" / "covers").mkdir(parents=True)
            (root / "library" / "pdfs" / "public.pdf").write_bytes(b"%PDF-1.4\n")
            (root / "library" / "covers" / "public.webp").write_bytes(b"RIFF")
            books = [
                {
                    "id": "public-book",
                    "title": "Public </script><script>alert(1)</script>",
                    "author": "Author",
                    "category": "Guide",
                    "published_at": "2026-08-23",
                    "description": "Public description",
                    "pdf": "library/pdfs/public.pdf",
                    "cover": "library/covers/public.webp",
                    "published": True,
                    "sort_order": 2,
                },
                {
                    "id": "draft-book",
                    "title": "Secret draft",
                    "author": "Author",
                    "category": "Draft",
                    "published_at": "2026-08-24",
                    "description": "Must not appear",
                    "pdf": "library/pdfs/public.pdf",
                    "cover": "",
                    "published": False,
                    "sort_order": 1,
                },
            ]
            (root / "data" / "books.json").write_text(json.dumps(books), encoding="utf-8")
            count = build_site(root)
            html = (root / "dist" / "index.html").read_text(encoding="utf-8")
            manifest = json.loads((root / "dist" / "catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(1, count)
            self.assertEqual(["public-book"], [book["id"] for book in manifest])
            self.assertNotIn("Secret draft", html)
            self.assertNotIn("</script><script>", html)
            self.assertIn("\\u003c/script>", html)
            self.assertTrue((root / "dist" / "library" / "pdfs" / "public.pdf").is_file())
            self.assertTrue((root / "dist" / "favicon.svg").is_file())


if __name__ == "__main__":
    unittest.main()
