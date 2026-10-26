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

    def test_public_shelf_has_real_planks_and_accessible_cover_motion(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "static" / "site.js").read_text(encoding="utf-8")
        style = (root / "static" / "site.css").read_text(encoding="utf-8")

        for marker in ("book-card", "book-stage", "book-display", "book-volume"):
            self.assertIn(marker, script)
        compact = style.replace(" ", "")
        self.assertIn("object-fit:contain", compact)
        self.assertIn(".book-stage::before", style)
        self.assertIn(".book-stage::after", style)
        self.assertIn("transform-origin:leftcenter", compact)
        self.assertIn("@media(hover:hover)and(pointer:fine)", compact)
        self.assertIn(".book-card:hover .book-cover", style)
        self.assertIn(".cover-button:focus-visible .book-cover", style)
        self.assertIn("@media(prefers-reduced-motion:reduce)", compact)
        reduced = style.split("@media (prefers-reduced-motion:reduce)", 1)[1]
        self.assertIn("rotateY(-7deg)", reduced)
        self.assertIn(".18s", reduced)

    def test_public_reader_opens_static_flip_viewer_by_catalog_id(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "index.html").read_text(encoding="utf-8")
        script = (root / "static" / "site.js").read_text(encoding="utf-8")

        self.assertIn('id="reader-frame"', template)
        self.assertIn("viewer.html?id=", script)
        self.assertIn("encodeURIComponent(book.id)", script)
        self.assertNotIn("book.pdf}#view=FitH", script)
        self.assertIn("frame.src = 'about:blank'", script)

    def test_static_viewer_uses_catalog_lookup_and_local_flip_dependencies(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "viewer.html").read_text(encoding="utf-8")
        script = (root / "static" / "viewer.js").read_text(encoding="utf-8")

        for marker in ('id="status"', 'id="book"', 'id="previous"', 'id="next"',
                       'id="page-number"', 'id="fullscreen"', 'id="original-pdf"'):
            self.assertIn(marker, html)
        self.assertIn('assets/vendor/page-flip.browser.js', html)
        self.assertIn('assets/viewer.js', html)
        self.assertIn("fetch('catalog.json'", script)
        self.assertIn("export function parseBookId", script)
        self.assertIn("export function findCatalogBook", script)
        self.assertIn("./vendor/pdfjs/pdf.mjs", script)
        self.assertIn("./vendor/pdfjs/pdf.worker.mjs", script)
        self.assertIn("./vendor/pdfjs/cmaps/", script)
        self.assertIn("./vendor/pdfjs/standard_fonts/", script)
        self.assertIn("./vendor/pdfjs/wasm/", script)
        self.assertIn("isEvalSupported: false", script)
        self.assertIn("window.St.PageFlip", script)
        self.assertIn("pagehide", script)
        self.assertIn("destroy", script)
        self.assertNotRegex(html + script, r'''(?:src|href)=["']/''')

    def test_static_viewer_id_validation_is_fail_closed(self):
        root = Path(__file__).resolve().parents[1]
        viewer = (root / "static" / "viewer.js").resolve().as_uri()
        program = f"""
          import {{parseBookId, findCatalogBook}} from {json.dumps(viewer)};
          const bad = ['', '../../private', '/absolute', 'https://example.invalid/x', 'A', 'ภาษาไทย', 'ok/id'];
          for (const value of bad) {{
            let rejected = false;
            try {{ parseBookId(new URLSearchParams({{id: value}})); }} catch (_) {{ rejected = true; }}
            if (!rejected) process.exit(10);
          }}
          let duplicateRejected = false;
          try {{ parseBookId(new URLSearchParams('id=book&id=other')); }} catch (_) {{ duplicateRejected = true; }}
          if (!duplicateRejected) process.exit(11);
          const id = parseBookId(new URLSearchParams({{id: 'book-1'}}));
          const book = findCatalogBook([{{id:'book-1', pdf:'library/pdfs/a.pdf'}}], id);
          if (book.pdf !== 'library/pdfs/a.pdf') process.exit(12);
          let unknownRejected = false;
          try {{ findCatalogBook([], 'book-1'); }} catch (_) {{ unknownRejected = true; }}
          if (!unknownRejected) process.exit(13);
        """
        subprocess.run(["node", "--input-type=module", "--eval", program], check=True, capture_output=True, text=True)

    def test_flip_viewer_has_no_top_header_and_uses_compact_bottom_icon_bar(self):
        root = Path(__file__).resolve().parents[1]
        index = (root / "templates" / "index.html").read_text(encoding="utf-8")
        viewer = (root / "templates" / "viewer.html").read_text(encoding="utf-8")
        site_script = (root / "static" / "site.js").read_text(encoding="utf-8")
        viewer_script = (root / "static" / "viewer.js").read_text(encoding="utf-8")
        site_style = (root / "static" / "site.css").read_text(encoding="utf-8")
        viewer_style = (root / "static" / "viewer.css").read_text(encoding="utf-8")

        self.assertNotIn('class="viewer-header"', viewer)
        self.assertNotIn("BOOK SHELF · FLIP CATALOGUE", viewer)
        self.assertNotIn('id="viewer-title"', viewer)
        self.assertNotIn('id="viewer-meta"', viewer)
        self.assertIn('id="back-shelf"', viewer)
        self.assertIn('id="original-pdf"', viewer)
        self.assertIn('class="icon-button"', viewer)
        self.assertIn('<svg', viewer)
        self.assertLess(viewer.index('id="back-shelf"'), viewer.index('</nav>'))
        self.assertLess(viewer.index('id="original-pdf"'), viewer.index('</nav>'))
        self.assertNotIn('class="reader-bar"', index)
        self.assertIn('class="reader-close"', index)
        self.assertNotIn("#reader-title", site_script)
        self.assertNotIn("#reader-meta", site_script)
        self.assertNotIn("#reader-download", site_script)
        self.assertIn("bookshelf-close-viewer", site_script)
        self.assertIn("#back-shelf", viewer_script)
        self.assertIn("bookshelf-close-viewer", viewer_script)
        self.assertIn("#reader-frame{width:100%;height:100%", site_style.replace(" ", ""))
        self.assertIn("height:calc(100dvh - 64px)", viewer_style)
        self.assertIn("width:40px", viewer_style)
        self.assertIn("const availableHeight", viewer_script)
        self.assertIn("const maxPageWidth", viewer_script)
        self.assertIn("maxHeight: Math.round(maxPageWidth * ratio)", viewer_script)
        self.assertIn("ui.status.classList.toggle('ready'", viewer_script)
        self.assertIn(".reader-status.ready{opacity:0", viewer_style.replace(" ", ""))

    def test_flip_viewer_uses_centered_page_cascade_while_loading(self):
        root = Path(__file__).resolve().parents[1]
        viewer = (root / "templates" / "viewer.html").read_text(encoding="utf-8")
        script = (root / "static" / "viewer.js").read_text(encoding="utf-8")
        style = (root / "static" / "viewer.css").read_text(encoding="utf-8")

        self.assertIn('id="status-copy"', viewer)
        self.assertIn('class="page-cascade"', viewer)
        self.assertEqual(viewer.count('class="page-cascade__sheet"'), 3)
        self.assertIn("statusText: document.querySelector('#status-copy')", script)
        self.assertIn("classList.toggle('is-loading', loading)", script)
        self.assertIn("message.startsWith('กำลัง')", script)
        compact_style = style.replace(" ", "")
        self.assertIn(".reader-status.is-loading{", compact_style)
        self.assertIn("top:calc((100dvh-64px)/2)", compact_style)
        self.assertIn("@keyframespage-cascade-flip", compact_style)
        self.assertIn(".reader-status.is-loading.status-copy", compact_style)
        self.assertIn("@media(prefers-reduced-motion:reduce)", compact_style)

    def test_flip_viewer_wheel_zoom_switches_to_bounded_pan_mode(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "viewer.html").read_text(encoding="utf-8")
        script_path = root / "static" / "viewer.js"
        script = script_path.read_text(encoding="utf-8")
        style = (root / "static" / "viewer.css").read_text(encoding="utf-8")

        self.assertIn('id="interaction-mode"', html)
        self.assertIn('class="zoom-icon"', html)
        self.assertIn('class="pan-icon"', html)
        self.assertIn("'wheel', onWheel, {passive: false}", script)
        self.assertIn("setPointerCapture", script)
        self.assertIn("classList.toggle('pan-mode'", script)
        self.assertIn(".pan-mode .zoom-icon", style)
        self.assertIn(".pan-mode .pan-icon", style)
        compact_style = style.replace(" ", "")
        self.assertIn(".book-viewport{width:100%;height:100%", compact_style)
        self.assertIn("touch-action:none", compact_style)
        self.assertIn("const touchPointers = new Map()", script)
        self.assertIn("const DOUBLE_TAP_DELAY", script)
        self.assertIn("event.pointerType === 'touch'", script)
        self.assertIn("event.stopPropagation()", script)
        self.assertIn("const touchStarts = new Map()", script)
        self.assertIn("'touchend', onTouchEndGuard", script)
        self.assertIn("disableFlipByClick: coarsePointer", script)
        program = f"""
          import {{nextZoom, clampPan, pinchZoom, panForPinch}} from {json.dumps(script_path.resolve().as_uri())};
          if (nextZoom(1, -100) !== 1.1) process.exit(10);
          if (nextZoom(2.5, -100) !== 2.5) process.exit(11);
          if (nextZoom(1.1, 100) !== 1) process.exit(12);
          const pan = clampPan({{x: 500, y: -500}}, {{x: 120, y: 80}});
          if (pan.x !== 120 || pan.y !== -80) process.exit(13);
          if (pinchZoom(1, 100, 180) !== 1.8) process.exit(14);
          if (pinchZoom(2, 100, 200) !== 2.5) process.exit(15);
          const anchored = panForPinch({{x:0,y:0}}, {{x:150,y:250}}, {{x:170,y:270}}, {{x:200,y:300}}, 1, 2);
          if (anchored.x !== 70 || anchored.y !== 70) process.exit(16);
        """
        subprocess.run(["node", "--input-type=module", "--eval", program],
                       check=True, capture_output=True, text=True)

    def test_flip_viewer_plays_selected_old_book_sound_after_page_change(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "templates" / "viewer.html").read_text(encoding="utf-8")
        script = (root / "static" / "viewer.js").read_text(encoding="utf-8")
        notice = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        sound = root / "static" / "sounds" / "old-book-page.mp3"

        self.assertIn('id="page-turn-sound"', html)
        self.assertIn('src="assets/sounds/old-book-page.mp3"', html)
        self.assertIn("pageTurnSound.play()", script)
        self.assertIn("event.data !== currentPage", script)
        self.assertTrue(sound.is_file())
        self.assertEqual("9d7fdd649382eace6876f1a3f4255d4f547624992f57c0e1ed974d8ff8ab8c0d",
                         __import__("hashlib").sha256(sound.read_bytes()).hexdigest())
        self.assertIn("CC0 1.0", notice)
        self.assertIn("paper-fabric-page-turn-66", notice)

        with tempfile.TemporaryDirectory() as tmp:
            build_root = Path(tmp)
            (build_root / "data").mkdir()
            (build_root / "library" / "pdfs").mkdir(parents=True)
            (build_root / "library" / "covers").mkdir(parents=True)
            (build_root / "data" / "books.json").write_text("[]\n", encoding="utf-8")
            build_site(build_root)
            built = build_root / "dist" / "assets" / "sounds" / "old-book-page.mp3"
            self.assertTrue(built.is_file())
            self.assertEqual(sound.read_bytes(), built.read_bytes())

    def test_build_site_copies_complete_static_viewer_runtime_and_licenses(self):
        resource_root = Path(__file__).resolve().parents[1]
        source_vendor = resource_root / "static" / "vendor"
        self.assertTrue((source_vendor / "licenses" / "page-flip-LICENSE").is_file())
        self.assertTrue((source_vendor / "licenses" / "pdfjs-LICENSE").is_file())
        self.assertTrue((source_vendor / "pdfjs" / "pdf.mjs").is_file())
        self.assertTrue((source_vendor / "pdfjs" / "pdf.worker.mjs").is_file())
        for directory in ("cmaps", "standard_fonts", "wasm"):
            self.assertTrue((source_vendor / "pdfjs" / directory).is_dir())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "library" / "pdfs").mkdir(parents=True)
            (root / "library" / "covers").mkdir(parents=True)
            (root / "data" / "books.json").write_text("[]\n", encoding="utf-8")
            build_site(root)
            for path in ("viewer.html", "assets/viewer.css", "assets/viewer.js",
                         "assets/vendor/page-flip.browser.js"):
                self.assertTrue((root / "dist" / path).is_file(), path)
            source_files = {path.relative_to(source_vendor) for path in source_vendor.rglob("*") if path.is_file()}
            built_files = {path.relative_to(root / "dist" / "assets" / "vendor")
                           for path in (root / "dist" / "assets" / "vendor").rglob("*") if path.is_file()}
            self.assertEqual(source_files, built_files)
            for path in source_files:
                self.assertEqual((source_vendor / path).read_bytes(),
                                 (root / "dist" / "assets" / "vendor" / path).read_bytes())


if __name__ == "__main__":
    unittest.main()
