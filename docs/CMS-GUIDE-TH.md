# แนวทาง Book Shelf CMS

## 1. เหตุผลที่แยก Public Site กับ Admin

GitHub Pages ให้บริการเฉพาะไฟล์ static จึงไม่สามารถรัน PHP, Python, session หรือฐานข้อมูลได้ หากใส่ username/password ใน JavaScript ของหน้าเว็บ รหัสผ่านจะถูกดาวน์โหลดไปยัง browser และผู้ใช้สามารถเปิดดูได้

โครงการนี้จึงแบ่งเป็นสองส่วน:

1. **Local Admin** — Python server ที่ bind เฉพาะ `127.0.0.1` ใช้ username/password, session และ CSRF
2. **Public Site** — HTML/CSS/JavaScript/PDF ที่สร้างลง `dist/` และ deploy ด้วย GitHub Actions

ผู้ดูแลได้ CMS ที่ใช้ง่าย ขณะที่เว็บไซต์ยังใช้ URL ของ GitHub Pages และไม่ต้องมี backend รายเดือน

## 2. Data flow

```text
Local Admin
  ├─ validate metadata ──> data/books.json
  ├─ validate upload ────> library/pdfs + library/covers
  ├─ build ──────────────> dist/ (local preview)
  └─ publish ────────────> git commit + push
                                  │
                                  ▼
GitHub Actions: unit tests → static build → Pages deploy
                                  │
                                  ▼
Public reader: index.html + catalog.json + PDF/cover assets
```

`data/books.json` เป็น source of truth เพียงชุดเดียว หน้าเว็บที่สร้างแล้วไม่ควรถูกแก้ด้วยมือ

## 3. รูปแบบข้อมูล

```json
{
  "id": "example-book",
  "title": "Example Book",
  "author": "Example Author",
  "category": "Guide",
  "published_at": "2026-08-23",
  "description": "คำอธิบาย",
  "pdf": "library/pdfs/<random>.pdf",
  "cover": "library/covers/<random>.webp",
  "published": true,
  "sort_order": 1
}
```

Builder จะกรอง Draft ออก ตรวจว่าไฟล์ของรายการ Published มีอยู่จริง เรียงด้วย `sort_order` และ escape JSON ก่อนฝังใน HTML

## 4. Authentication

- Username และ salted password hash เก็บใน `.admin-config.json` หรือ path จาก `BOOKSHELF_CMS_CONFIG`
- ใช้ `hashlib.scrypt` (`N=32768`, `r=8`, `p=1`) และ random salt 16 bytes
- เปรียบเทียบด้วย constant-time comparison
- Session token/CSRF token สุ่มและเก็บใน memory; ปิด server แล้ว session หาย
- Cookie เป็น `HttpOnly; SameSite=Strict`
- Login มี rate limit แบบง่าย 8 ครั้งต่อ 5 นาที
- Server bind ที่ `127.0.0.1` เท่านั้น

เพราะ Admin ใช้งานบน loopback จึงไม่ส่ง password ผ่านเครือข่าย หากต้องการใช้ข้ามอุปกรณ์ ต้องออกแบบ HTTPS/reverse proxy/firewall ใหม่ ไม่ควรเปลี่ยน bind address อย่างเดียว

## 5. Upload safety

- สร้างชื่อไฟล์ใหม่ด้วย random 128-bit token
- PDF: `.pdf`, สูงสุด 50 MB และต้องเริ่มด้วย `%PDF-`
- ปก: PNG/JPEG/WebP/GIF, สูงสุด 8 MB และ signature ต้องตรงกับนามสกุล
- Catalog อนุญาต path ตรงภายใน `library/pdfs/` หรือ `library/covers/` เท่านั้น
- ไม่รองรับ executable uploads
- การนำ record ออกจาก catalog จะไม่ลบไฟล์ เพื่อป้องกัน destructive action โดยไม่ตั้งใจ

## 6. Publish safety

ปุ่ม Publish ทำงานเฉพาะ branch `main` และ stage เฉพาะ:

```text
data/books.json
library/pdfs/
library/covers/
```

จากนั้น commit/push ผ่าน Git credential ของเครื่อง GitHub Actions เป็นผู้สร้างและ deploy `dist/` ใหม่ จึงไม่ต้องให้ CMS เก็บ token

## 7. จาก PHP starter เดิมสู่งานนี้

แนวคิดที่คงไว้จากชุดตัวอย่าง:

- server-side authentication แทน password ใน client
- catalog source of truth
- published/draft state
- category, ordering และ search
- upload size/type/path validation
- CSRF และ output escaping
- public gallery แยกจาก Admin
- native PDF fallback

สิ่งที่เปลี่ยนเพื่อรองรับ GitHub Pages:

- PHP/MySQL → Python local server + JSON catalog
- Google OAuth → local username/password
- runtime database → static build
- online uploads → local uploads แล้ว commit/push
- public PHP viewer → browser-native PDF iframe/link

## 8. Backup และ restore

สำรองอย่างน้อย:

- Git repository ทั้งหมด (รวม `data/` และ `library/`)
- `.admin-config.json` แยกจาก Git หรือ setup username/password ใหม่หลัง restore

Git history เป็นประวัติ catalog/assets แต่ไม่ควรถือเป็น backup เดียวสำหรับ PDF จำนวนมาก

## 9. การขยายในอนาคต

เมื่อ library โตขึ้น สามารถเพิ่มได้โดยไม่เปลี่ยนหน้าสาธารณะมาก:

- thumbnail generation สำหรับ PDF ที่ไม่มีปก
- tags/collections เพิ่มใน schema พร้อม migration/test
- object storage สำหรับ PDF ขนาดใหญ่
- full-text PDF indexing แบบ build-time
- offline/PWA cache เฉพาะ cover และ catalog
- online Admin backend พร้อม HTTPS หากมีความจำเป็นจริง
