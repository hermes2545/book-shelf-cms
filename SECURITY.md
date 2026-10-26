# Security Policy

Book Shelf CMS is designed for a single administrator on a trusted local computer.

- Keep the admin server bound to `127.0.0.1`.
- Do not commit `.admin-config.json`, passwords, access tokens, cookies, or local paths.
- Published PDFs and covers are public. Draft is catalog visibility, not access control.
- Use a unique password of at least 10 characters.
- Keep Python, Git, and the operating system patched.
- Review staged files before a manual push when changing code outside the CMS.

For security reports, use a private channel to the repository owner. Do not open a public issue containing credentials or private document links.
