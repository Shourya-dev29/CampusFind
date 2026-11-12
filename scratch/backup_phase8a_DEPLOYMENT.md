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
| `DATABASE_PATH` | Recommended | `database/campusfind.db` | Persistent filesystem path to the SQLite database file. |
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

