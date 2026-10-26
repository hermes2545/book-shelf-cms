# Third-party notices

The static Flip Viewer redistributes these browser dependencies from the user-supplied Generic Catalogue CMS reference archive:

- **PDF.js / `pdfjs-dist` 6.4.299** — Apache License 2.0 — https://github.com/mozilla/pdf.js
- **StPageFlip / `page-flip` 2.0.7** — MIT License — https://github.com/Nodlik/StPageFlip
- **Old Book Page Turning 66 sound effect** — CC0 1.0 — https://sfxmint.com/sounds/paper-fabric-page-turn-66

The complete vendor runtime is stored under `static/vendor/` and copied byte-for-byte to `dist/assets/vendor/` during the static build. License texts remain beside the redistributed code:

- `static/vendor/licenses/`
- `static/vendor/pdfjs/cmaps/LICENSE`
- `static/vendor/pdfjs/standard_fonts/`
- `static/vendor/pdfjs/wasm/`

The selected page-turn sound is stored at `static/sounds/old-book-page.mp3` and copied to `dist/assets/sounds/` during the static build.

Do not remove these notices or license files when updating the vendored dependencies.
