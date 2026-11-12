# CampusFind — Production Deployment & Operations Guide

This guide describes how to configure, secure, operate, and deploy the **CampusFind** college lost-and-found web portal in both local environments and production hosting.

---

## 1. Required & Optional Environment Variables

All settings are managed via environment variables. Copy `.env.example` to `.env` to configure your environment:

| Variable | Required in Production? | Default Value | Description |
| :--- | :---: | :--- | :--- |
| `CAMPUSFIND_ENV` | Yes | `development` | Set to `production` for live deployments. Enforces strict secret key rules. |
| `SECRET_KEY` | **Yes (Crucial)** | *None in prod* | Cryptographic signing key (minimum 32 characters, 64-char hex recommended). |
| `SESSION_COOKIE_SECURE` | Yes (for HTTPS) | `true` in prod, `false` in dev | When `true`, session cookies are only transmitted over TLS/HTTPS connections. |
| `DATABASE_URL` | Yes (for Cloud/Postgres) | *None (uses SQLite)* | PostgreSQL connection string. Use Direct (5432) or Session Pooler (5432) with `?sslmode=require`. |
| `DATABASE_PATH` | For local SQLite | `database/campusfind.db` | Local filesystem path to the SQLite database file when `DATABASE_URL` is empty. |
| `UPLOAD_FOLDER` | Recommended | `static/uploads` | Persistent directory path for student-uploaded photographs. |
| `RATELIMIT_STORAGE_URI` | Optional | `memory://` | Storage backend for rate limiting. Use `redis://host:port` for multi-worker clusters. |
| `BEHIND_PROXY` | If using reverse proxy | `false` | Enables Werkzeug `ProxyFix` (for Nginx, Caddy, Cloudflare, Traefik, AWS ALB). |

---

## 2. Generating & Configuring `SECRET_KEY`

In production mode (`CAMPUSFIND_ENV=production`), CampusFind **strictly refuses to start** if `SECRET_KEY` is missing, predictable, or fewer than 32 characters.

### Generate a Strong Secret Key
Run this command in Python:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
*Output example: `c7a4e61b9f8d3e20a5c1b849204856e7293a4c5d6e7f8091a2b3c4d5e6f7a8b9`*

Never commit your generated key to source control or share it publicly.

---

## 3. How to Run Locally (Development)

### Windows (PowerShell)
```powershell
# 1. Activate Virtual Environment
.\venv\Scripts\Activate.ps1

# 2. Run Flask Development Server
python app.py
```
Portal will be active at: `http://127.0.0.1:5000`

### Linux / macOS
```bash
source venv/bin/activate
python app.py
```

---

## 4. How to Run with a Production WSGI Server

In production, never use Flask's built-in development server (`app.run()`), as it is single-threaded and not designed for security or high concurrency.

### Linux / UNIX Host (Gunicorn)
Use Gunicorn with 3–4 worker processes:
```bash
# Set environment variables
export CAMPUSFIND_ENV="production"
export SECRET_KEY="your-generated-64-character-hex-key"
export SESSION_COOKIE_SECURE="true"
export BEHIND_PROXY="true"

# Start Gunicorn WSGI server
gunicorn -w 4 -b 0.0.0.0:8000 --access-logfile - --error-logfile - "app:app"
```

### Windows Production Host (Waitress)
Because Gunicorn does not run on Windows, use Waitress if hosting on Windows Server:
```bash
pip install waitress
waitress-serve --port=8000 app:app
```

---

## 5. HTTPS & Cookie Security Configuration

1. **SSL/TLS Termination:** Always terminate HTTPS at your reverse proxy (Nginx, Caddy, or Cloudflare).
2. **`SESSION_COOKIE_SECURE = True`:** Ensures browser refuses to send authentication cookies over insecure HTTP connections.
3. **`SESSION_COOKIE_HTTPONLY = True`:** Blocks client-side JavaScript from accessing cookies (mitigating XSS attacks).
4. **`SESSION_COOKIE_SAMESITE = 'Lax'`:** Protects against cross-site request forgery when navigating from external links.

---

## 6. Database & Upload Persistence Requirements

CampusFind uses **SQLite** for relational storage and **local filesystem storage** for item images.

### Persistence Rule (Container & Cloud Caveat)
> [!CAUTION]
> If deploying to cloud platforms with ephemeral filesystems (e.g., standard Heroku, basic Render web services, or standard Docker containers without volumes), any dyno restart or redeployment **will wipe SQLite database records and uploaded photos** unless mounted on a persistent disk!

### Ensuring Persistence:
1. **Docker / Container Deployments:** Mount host directories or Docker Named Volumes:
   ```yaml
   volumes:
     - campusfind_db:/app/database
     - campusfind_uploads:/app/static/uploads
   ```
2. **VPS Deployments (DigitalOcean, Linode, AWS EC2, Hetzner):** Normal filesystem storage is persistent by default. Ensure the directory permissions allow the application user read/write access:
   ```bash
   chmod -R 750 /var/www/campusfind/database
   chmod -R 750 /var/www/campusfind/static/uploads
   ```

### When to Migrate to PostgreSQL:
- When traffic exceeds ~50 concurrent write operations per second.
- When running multiple horizontal application instances (multiple servers or pods behind a load balancer).
- When managed cloud databases with automated point-in-time recovery are required.

---

## 7. Backup and Restore Procedures

### Automated Database Backup
Run this backup command (or configure it as a daily cron job):
```bash
# SQLite Online Safe Backup (locks safely during snapshot)
sqlite3 database/campusfind.db ".backup 'database/backup_$(date +%Y%m%d_%H%M%S).db'"
```

### Uploaded Photographs Backup
Synchronize uploaded images to an off-site backup or archive:
```bash
tar -czvf "uploads_backup_$(date +%Y%m%d).tar.gz" static/uploads/
```

### Restore Procedure
1. Stop the application server (`systemctl stop campusfind` or `docker compose down`).
2. Restore the database file:
   ```bash
   cp database/backup_20261111_090000.db database/campusfind.db
   ```
3. Verify integrity:
   ```bash
   sqlite3 database/campusfind.db "PRAGMA integrity_check;"
   # Output should be: ok
   ```
4. Restart the application server.

---

## 8. Rate Limiting Configuration & Reverse Proxies

To protect against credential-stuffing and brute-force password guessing, CampusFind enforces rate limits on authentication endpoints:
- `/login`: 10 requests per minute, 30 per hour per IP.
- `/admin/login`: 10 requests per minute, 30 per hour per IP.
- `/register`: 10 requests per minute, 30 per hour per IP.

### Running Behind a Reverse Proxy (Nginx / Cloudflare)
When CampusFind is behind a reverse proxy, all requests might appear to originate from `127.0.0.1` unless client IP forwarding is enabled.
1. In your proxy (e.g., Nginx), set proxy headers:
   ```nginx
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   proxy_set_header X-Forwarded-Proto $scheme;
   proxy_set_header Host $http_host;
   ```
2. In your `.env`, set:
   ```ini
   BEHIND_PROXY=true
   ```
   CampusFind uses Werkzeug's `ProxyFix` middleware to resolve the genuine client IP address.

---

## 9. Suitable Hosting Options Comparison

| Option | Ease of Setup | Persistence Handling | Scalability | Recommendation |
| :--- | :---: | :--- | :---: | :--- |
| **Linux VPS (DigitalOcean / Linode / Hetzner)** | Moderate | Native persistent filesystem. Simple to backup with cron. | Vertical scaling | ⭐ **Highly Recommended** for college campus deployments. Low cost ($5/mo), full control. |
| **PaaS with Persistent Disk (Render / Railway / Fly.io)** | Easy | Requires attaching a **Persistent Disk Volume** mounted at `/app/database` and `/app/static/uploads`. | Single instance with disk | Recommended if cloud container management is preferred. |
| **Ephemeral PaaS (Free Heroku / Standard Vercel)** | Easy | ⚠️ **DO NOT USE** with SQLite: database and images disappear on restart. | High | Incompatible with SQLite without object storage (AWS S3) & external PostgreSQL. |

---

## 10. Post-Deployment Verification Checklist

Execute this checklist immediately after going live:

- [ ] **Health Check:** `curl -i https://yourdomain.edu/health` returns `HTTP/200 OK` with `{"status": "healthy"}`.
- [ ] **HTTPS Redirection:** Browsing `http://yourdomain.edu` automatically redirects to `https://`.
- [ ] **Cookie Flags:** Inspect session cookie in browser dev tools: verify `HttpOnly`, `SameSite=Lax`, and `Secure` flags are checked.
- [ ] **Defensive Headers:** Verify `X-Frame-Options: SAMEORIGIN` and `X-Content-Type-Options: nosniff` are present.
- [ ] **Secret Key Protection:** Verify the application fails to start if `SECRET_KEY` is unset in production.
- [ ] **Admin Account:** Run `python create_admin.py` to create the initial campus administrator account securely.
- [ ] **Image Upload Test:** Report an item with a photo; verify it displays on [`/item/<id>`](file:///c:/Users/Asus/Desktop/CampusFind/templates/detail.html).
- [ ] **Rate Limit Test:** Rapidly attempt 11 logins to verify the 429 response renders properly.
- [ ] **404 Handling:** Visit `https://yourdomain.edu/item/999999` to verify custom 404 page renders.
- [ ] **Backup Verification:** Run test backup script and confirm `.db` file validity with `PRAGMA integrity_check`.

---

## 11. Supabase Storage Integration (Phase 8A)

CampusFind uses **Supabase Storage** for scalable, durable cloud asset storage. Uploaded photographs are stored in a private bucket and served securely using time-limited signed URLs.

### 11.1 Required Environment Variables

Configure these variables in your `.env` (development) or hosting provider's environment variables (production):

| Variable | Required? | Default | Description |
| :--- | :---: | :--- | :--- |
| `SUPABASE_URL` | Yes (for cloud storage) | *None* | Project URL (e.g. `https://xyzcompany.supabase.co`). Found in Supabase Settings > API. |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes (for cloud storage) | *None* | Service Role secret key for backend storage access. **Never expose to frontend!** |
| `SUPABASE_BUCKET` | Optional | `campusfind-uploads` | Name of the private storage bucket in Supabase. |
| `SUPABASE_SIGNED_URL_EXPIRY` | Optional | `3600` | Expiration lifetime for generated signed URLs in seconds (1 hour). |
| `SUPABASE_FALLBACK_LOCAL` | Optional | `false` | When `true` in non-production, falls back to local disk if cloud upload fails. |

> [!CAUTION]
> **Keep `SUPABASE_SERVICE_ROLE_KEY` strictly confidential.** It has full administrative bypass access to your Supabase project. Never paste it in chat, commit it to GitHub, or inject it into client-side templates or JavaScript.

### 11.2 Private Bucket Setup in Supabase Dashboard

1. Navigate to your **Supabase Dashboard** > **Storage**.
2. Click **New bucket**.
3. Bucket name: **`campusfind-uploads`**.
4. Set **Public bucket** to **OFF** (Keep the bucket **Private**).
5. File size limit: **5 MB**.
6. Allowed MIME types: `image/jpeg`, `image/png`, `image/gif`, `image/webp`.
7. Click **Save bucket**.

### 11.3 How Image Upload & Signed URLs Work

1. **Upload (`/report/<type>`):**
   - The user selects an image and submits the report form.
   - Flask validates the file extension and binary magic bytes (rejecting fake PNGs or HTML).
   - If Supabase is configured, Flask streams the image bytes directly to `campusfind-uploads` using `SUPABASE_SERVICE_ROLE_KEY`.
   - The unique filename (e.g., `1762859123_a1b2c3d4.jpg`) is saved in the SQLite `items.photo` column.
   - If Supabase is not configured, Flask saves the file locally in `static/uploads/`.
2. **Display (`/static/uploads/<filename>`):**
   - Templates continue requesting `/static/uploads/<filename>`.
   - Flask first checks if the file exists on the local filesystem (preserving existing photos).
   - If not local, Flask calls `supabase.storage.from_("campusfind-uploads").create_signed_url(filename, expires_in=3600)`.
   - The browser is redirected (HTTP 302) to the temporary secure signed URL.
   - If the file does not exist or Supabase is unreachable, Flask renders the standard 404 page.

### 11.4 Local Development Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Populate `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in your `.env`.
3. Launch Flask locally:
   ```bash
   python app.py
   ```
4. `python-dotenv` automatically loads your credentials into `os.environ`.

### 11.5 Production Deployment Setup (Render / VPS)

1. **Render / Railway / Cloud PaaS:**
   - Add `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_BUCKET` to your Web Service Environment Variables.
2. **Linux VPS (systemd service):**
   - Add environment directives to your `/etc/systemd/system/campusfind.service`:
     ```ini
     Environment="SUPABASE_URL=https://your-ref.supabase.co"
     Environment="SUPABASE_SERVICE_ROLE_KEY=your-service-role-key"
     Environment="SUPABASE_BUCKET=campusfind-uploads"
     ```
   - Run `systemctl daemon-reload && systemctl restart campusfind`.

### 11.6 Troubleshooting Supabase Storage

- **Error: `Invalid file. Only genuine image files under 5 MB are allowed.`**
  The uploaded file failed either the extension check or the magic-byte header inspection.
- **Error: `Image upload service is currently unavailable.`**
  - Verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are correct.
  - Verify bucket `campusfind-uploads` exists in your Supabase project.
  - Check network egress from your host to `*.supabase.co`.
- **404 on image viewing:**
  - Verify the bucket is named `campusfind-uploads` and matches `SUPABASE_BUCKET`.
  - Check if the image was uploaded under an older local deployment without syncing.

---

## 12. Supabase PostgreSQL Connection Guidance (Phase 8C)

CampusFind is a persistent WSGI application (Flask + Gunicorn with multiple worker processes). Connecting to Supabase PostgreSQL requires selecting the correct connection mode for your deployment environment.

### 12.1 Connection Option Comparison

| Option | Host & Port Format | IPv4 / IPv6 | Recommended For | Notes |
| :--- | :--- | :---: | :--- | :--- |
| **Direct Connection** | `db.[REF].supabase.co:5432` | **IPv6 only** | VPS / Platforms with native IPv6 (Fly.io, Railway) | ⭐ **Preferred** when IPv6 is supported. Full native PostgreSQL feature set. |
| **Session Pooler** | `aws-0-[REGION].pooler.supabase.com:5432` | **IPv4 & IPv6** | Cloud PaaS with IPv4 egress (Render, AWS, DigitalOcean) | ⭐ **Recommended for Render**. Full session semantics; persistent connection per worker. |
| **Transaction Pooler** | `aws-0-[REGION].pooler.supabase.com:6543` | **IPv4 & IPv6** | Serverless / Edge Functions (AWS Lambda, Vercel) | ⚠️ **Do NOT recommend for Flask/Gunicorn**. Re-assigns connections after each transaction, breaking session state, prepared statements, and locks. |

### 12.2 How to Obtain Your Connection String in Supabase

1. Open your **Supabase Dashboard**.
2. Go to **Project Settings** (gear icon in left sidebar) > **Database**.
3. Scroll down to the **Connection string** section.
4. Select the **URI** tab.
5. Choose your mode:
   - For **Render / IPv4 environments**: Select **Session pooler** (Port `5432`).
   - For **IPv6 environments**: Select **Direct connection** (Port `5432`).
6. Copy the connection URI:
   ```
   postgresql://postgres.[YOUR-PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres?sslmode=require
   ```
7. Replace `[YOUR-PASSWORD]` with your actual Supabase database password.
8. Store this URI in your `.env` (local testing) or Render Web Service Environment Variables (`DATABASE_URL`).


