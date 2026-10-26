# Book Shelf CMS

ระบบชั้นหนังสือ PDF แบบ **local-first CMS**: หน้า Admin ทำงานเฉพาะเครื่องผู้ดูแล ส่วนเว็บไซต์สาธารณะสร้างเป็น static files และเผยแพร่ด้วย GitHub Pages

## URL

- เว็บไซต์: `https://hermes2545.github.io/book-shelf-cms/`
- Repository: `https://github.com/hermes2545/book-shelf-cms`
- Admin: `http://127.0.0.1:8765/admin/` (เปิดได้เฉพาะเครื่องที่รัน CMS)

## ความสามารถ

- Login ด้วย username + password
- เก็บรหัสผ่านเป็น salted `scrypt` hash นอก Git
- เพิ่ม/แก้ไข/นำรายการออกจาก catalog
- อัปโหลด PDF สูงสุด 50 MB และปกสูงสุด 8 MB
- ตรวจนามสกุลและ file signature ก่อนรับไฟล์
- Draft/Published, หมวดหมู่, วันที่ และลำดับ
- Search/filter หน้า Public พร้อมชั้นหนังสือจริงที่ปรับ 4/2/1 คอลัมน์ตามหน้าจอ
- เปิดปกด้วย mouse hover หรือ keyboard focus โดยรองรับ Reduce Motion
- เปิด PDF ด้วย Flip Viewer แบบ static ซึ่งใช้ PDF.js + StPageFlip หรือเลือกเปิด PDF ต้นฉบับเป็นทางสำรอง
- สร้าง preview และกด Publish ไป GitHub
- GitHub Actions ทดสอบและ deploy `dist/` เท่านั้น

> ไฟล์ที่ Published บน GitHub Pages เป็นสาธารณะ การตั้ง Draft ซ่อนรายการจาก catalog แต่ไม่ใช่ระบบเก็บเอกสารลับ

## เริ่มใช้งาน Admin

ต้องมี Python 3.11+ และ Git/GitHub authentication พร้อมใช้งาน

```bash
git clone https://github.com/hermes2545/book-shelf-cms.git
cd book-shelf-cms
python -m cms.server setup
python -m cms.server serve
```

เปิด `http://127.0.0.1:8765/admin/`

ไฟล์ `.admin-config.json` จะถูกสร้างในเครื่อง, permission `0600`, ถูก ignore และห้าม commit

### ใช้ผ่าน Tailscale

สำหรับเครื่องที่ติดตั้งโครงการนี้ ใช้ backend loopback พอร์ต `18765` และ Tailscale Serve HTTPS พอร์ต `8453`:

```bash
python -m cms.server serve --port 18765
tailscale serve --bg --https=8453 http://127.0.0.1:18765
```

เปิด `https://<TAILSCALE-DNS-NAME>:8453/admin/` จากอุปกรณ์ใน Tailnet เท่านั้น หากยังไม่มี admin config หน้า Setup ครั้งแรกจะให้สร้าง username/password และจะปิดตัวเองหลังบันทึกสำเร็จ ห้ามใช้ `tailscale funnel` กับหน้า Admin

### เปลี่ยนตำแหน่ง config

```bash
export BOOKSHELF_CMS_CONFIG="$HOME/.config/book-shelf-cms/admin.json"
python -m cms.server setup
python -m cms.server serve
```

## วิธีทำงาน

1. Login ที่ Local Admin
2. เพิ่มข้อมูล อัปโหลด PDF/ปก และบันทึก
3. เปิด `แสดงบนเว็บไซต์` สำหรับรายการที่พร้อมเผยแพร่
4. กด **สร้าง Preview** หรือรัน `python scripts/build.py`
5. ตรวจ `dist/index.html` ผ่าน local HTTP server
6. กด **Publish to GitHub**
7. CMS จะ stage เฉพาะ `data/books.json`, `library/pdfs/`, `library/covers/`, commit และ push `main`
8. GitHub Actions รันทดสอบ สร้าง `dist/` ใหม่ และ deploy GitHub Pages

## ทดสอบ

```bash
python -m unittest discover -s tests -v
python scripts/build.py
python -m compileall -q cms scripts
node --check static/site.js
```

## โครงสร้างสำคัญ

- `data/books.json` — source of truth ของรายการหนังสือ
- `library/pdfs/` — PDF สาธารณะ
- `library/covers/` — ปกสาธารณะ
- `cms/core.py` — validation, password hashing, catalog และ static build
- `cms/server.py` — local-only HTTP API, session, CSRF, uploads และ publish
- `cms/admin.html` — Admin UI
- `templates/index.html` — Public template
- `static/` — Public CSS/JavaScript
- `templates/viewer.html` — static Flip Viewer shell สำหรับ GitHub Pages
- `static/viewer.js` — catalog-ID validation, PDF.js rendering, StPageFlip และ resource cleanup
- `static/vendor/` — PDF.js, StPageFlip, CMaps, standard fonts, WASM และใบอนุญาต
- `THIRD_PARTY_NOTICES.md` — รุ่น แหล่งที่มา และใบอนุญาตของ runtime ภายนอก
- `scripts/build.py` — static-site generator
- `.github/workflows/pages.yml` — tests + GitHub Pages deployment
- `docs/CMS-GUIDE-TH.md` — แนวทางสถาปัตยกรรมและการดูแลระบบ

## ข้อจำกัด

- GitHub แนะนำให้ repository มีขนาดไม่เกิน 1 GB และไฟล์ทั่วไปใน Git ห้ามเกิน 100 MB; CMS จำกัด PDF ที่ 50 MB
- หากจำนวน/ขนาด PDF โตมาก ควรย้ายไฟล์ไป object storage แล้วเก็บ URL ใน catalog
- Admin จงใจ bind เฉพาะ `127.0.0.1`; อย่าเปลี่ยนเป็น `0.0.0.0` โดยไม่มี HTTPS, firewall และ authentication review
- ปุ่ม Publish ใช้ Git credential ที่มีอยู่ในเครื่อง ไม่เก็บ GitHub token ใน CMS

## License

MIT — ดู `LICENSE`
