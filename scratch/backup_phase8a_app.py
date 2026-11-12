from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort, jsonify, send_from_directory
import sqlite3
import os
import time
import secrets
import re
from datetime import date
from functools import wraps
from urllib.parse import urlparse, urljoin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# -------------------------------------------------------------
# Stage 2: Production Configuration & Secret Key Validation
# -------------------------------------------------------------

ENV_MODE = os.environ.get("CAMPUSFIND_ENV", os.environ.get("FLASK_ENV", "development")).lower()
IS_PRODUCTION = ENV_MODE in ("production", "prod")

secret_key_env = os.environ.get("SECRET_KEY")
if IS_PRODUCTION:
    # In production, refuse to start if a secure SECRET_KEY is missing or predictable
    if not secret_key_env or secret_key_env.strip() in (
        "",
        "campusfind-development-key",
        "campusfind-sec-token-dev-fallback-8f92b7c4",
        "change-this-to-a-strong-random-64-character-hex-key-in-production"
    ) or len(secret_key_env.strip()) < 32:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: A strong, non-predictable SECRET_KEY "
            "(minimum 32 characters) must be configured in environment variables for production mode! "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    app.secret_key = secret_key_env
else:
    app.secret_key = secret_key_env or "campusfind-sec-token-dev-fallback-8f92b7c4"

# Cookie Security & Upload Limit (5 MB)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

secure_cookie_env = os.environ.get("SESSION_COOKIE_SECURE", "").lower()
if secure_cookie_env in ("true", "1", "yes"):
    app.config["SESSION_COOKIE_SECURE"] = True
elif secure_cookie_env in ("false", "0", "no"):
    app.config["SESSION_COOKIE_SECURE"] = False
else:
    app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 Megabytes

# Reverse Proxy Support (Werkzeug ProxyFix)
if os.environ.get("BEHIND_PROXY", "").lower() in ("true", "1", "yes"):
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# -------------------------------------------------------------
# Stage 3: Rate Limiting
# -------------------------------------------------------------

ratelimit_env = os.environ.get("RATELIMIT_ENABLED", "true").lower()
ratelimit_enabled = ratelimit_env not in ("false", "0", "no")

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    default_limits=["500 per day", "120 per hour"],
    strategy="fixed-window",
    enabled=ratelimit_enabled
)

# -------------------------------------------------------------
# Stage 4: Persistent File Storage & Paths
# -------------------------------------------------------------

DATABASE = os.environ.get("DATABASE_PATH", "database/campusfind.db")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "static/uploads")

# Security & Validation Constants
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
VALID_CATEGORIES = {"Electronics", "Bags", "Wallets", "ID Cards", "Books", "Other"}
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def is_valid_email(email):
    """Validate email format according to standard RFC structure."""
    if not email or len(email) > 120:
        return False
    return bool(EMAIL_REGEX.match(email))


def is_safe_url(target):
    """Ensure redirect URLs stay strictly internal to prevent Open Redirect attacks."""
    if not target:
        return False
    target = target.strip()
    # Reject protocol-relative or backslash-tricked URLs
    if target.startswith("//") or target.startswith("\\"):
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def is_allowed_image(file_storage):
    """Validate both file extension and image header magic bytes."""
    if not file_storage or not file_storage.filename:
        return False
    filename = file_storage.filename
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False

    # Inspect magic bytes to prevent renamed HTML/SVG/executables
    header = file_storage.read(16)
    file_storage.seek(0)  # Rewind stream for subsequent save()
    if not header or len(header) < 4:
        return False

    # JPEG: FF D8 FF
    if ext in ("jpg", "jpeg") and header.startswith(b"\xff\xd8\xff"):
        return True
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if ext == "png" and header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    # GIF: GIF87a or GIF89a
    if ext == "gif" and (header.startswith(b"GIF87a") or header.startswith(b"GIF89a")):
        return True
    # WEBP: RIFF....WEBP
    if ext == "webp" and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return True

    return False


def get_db():
    """Get database connection with SQLite Foreign Key enforcement enabled."""
    conn = sqlite3.connect(DATABASE)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


@app.after_request
def apply_security_headers(response):
    """Inject defensive HTTP headers to prevent Clickjacking, MIME sniffing and leakage."""
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# -------------------------------------------------------------
# Semantic Error Handlers & Rate Limit Feedback
# -------------------------------------------------------------

@app.errorhandler(404)
def not_found_error(error):
    return render_template("404.html"), 404


@app.errorhandler(413)
def request_entity_too_large(error):
    return render_template("413.html"), 413


@app.errorhandler(429)
def ratelimit_exceeded(error):
    return render_template("429.html"), 429


@app.errorhandler(500)
def internal_error(error):
    return render_template("500.html"), 500


# -------------------------------------------------------------
# Stage 6: Minimal Monitoring & Health Check Endpoint
# -------------------------------------------------------------

@app.route("/health")
@app.route("/healthz")
def health_check():
    """Health check endpoint for monitoring, load balancers, and container probes."""
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return jsonify({
            "status": "healthy",
            "service": "CampusFind",
            "database": "connected"
        }), 200
    except Exception:
        return jsonify({
            "status": "unhealthy",
            "service": "CampusFind",
            "database": "disconnected"
        }), 503


def init_db():
    db_dir = os.path.dirname(DATABASE)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    conn = get_db()

    # 1. Items table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            report_type TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            item_date TEXT NOT NULL,
            email TEXT NOT NULL,
            photo TEXT,
            status TEXT DEFAULT 'Open',
            user_id INTEGER,
            is_archived INTEGER DEFAULT 0
        )
    """)

    # Safe migration: ensure user_id column exists
    try:
        conn.execute("ALTER TABLE items ADD COLUMN user_id INTEGER REFERENCES users(id)")
    except sqlite3.OperationalError:
        pass

    # Safe migration: ensure is_archived column exists
    try:
        conn.execute("ALTER TABLE items ADD COLUMN is_archived INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.execute("UPDATE items SET is_archived = 0 WHERE is_archived IS NULL")

    # 2. Users table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_admin INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
    """)

    # Safe migration: ensure is_admin column exists
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.execute("UPDATE users SET is_admin = 0 WHERE is_admin IS NULL")

    # Safe migration: ensure is_active column exists
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    conn.execute("UPDATE users SET is_active = 1 WHERE is_active IS NULL")

    # 3. Claims table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            claimant_id INTEGER NOT NULL,
            claim_reason TEXT NOT NULL,
            contact_info TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES items (id),
            FOREIGN KEY (claimant_id) REFERENCES users (id)
        )
    """)

    # 4. Notifications table (Phase 5)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            related_item_id INTEGER,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (related_item_id) REFERENCES items (id)
        )
    """)

    conn.commit()
    conn.close()


# Auto-initialize SQLite database schema on startup (works with both dev server and WSGI servers like Gunicorn)
try:
    init_db()
except Exception:
    pass


# -------------------------------------------------------------
# Uploaded Media Serving (Supports local storage & persistent cloud disk paths)
# -------------------------------------------------------------

@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    """Serve user uploaded photos from UPLOAD_FOLDER (supports local path and persistent cloud disks)."""
    return send_from_directory(os.path.abspath(UPLOAD_FOLDER), filename)


# -------------------------------------------------------------
# CSRF Security & Context Helpers
# -------------------------------------------------------------

@app.before_request
def ensure_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)


@app.context_processor
def inject_globals():
    unread_count = 0
    if "user_id" in session:
        try:
            conn = get_db()
            unread_count = conn.execute(
                "SELECT count(*) FROM notifications WHERE user_id = ? AND is_read = 0",
                (session["user_id"],)
            ).fetchone()[0]
            conn.close()
        except Exception:
            unread_count = 0

    return dict(
        csrf_token=session.get("csrf_token", ""),
        unread_notifications_count=unread_count
    )


def verify_csrf():
    """Verify CSRF token on destructive/POST management requests."""
    token = request.form.get("csrf_token")
    if not token or token != session.get("csrf_token"):
        abort(400, "CSRF verification failed: Missing or invalid security token.")


def login_required(view):
    """Decorator to require login with live database active status check."""
    @wraps(view)
    def wrapped_view(**kwargs):
        user_id = session.get("user_id")
        if not user_id:
            flash("Please log in to continue.")
            return redirect(url_for("login", next=request.url))

        # Live database check: account must exist and be active
        conn = get_db()
        user = conn.execute("SELECT id, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()

        if not user or user["is_active"] != 1:
            session.clear()
            flash("Your account has been deactivated. Please contact campus administration.")
            return redirect(url_for("login"))

        return view(**kwargs)
    return wrapped_view


def admin_required(view):
    """Decorator to protect administrative routes with live database privilege check."""
    @wraps(view)
    def wrapped_view(**kwargs):
        user_id = session.get("user_id")
        if not user_id:
            flash("Please log in with an administrator account.")
            return redirect(url_for("admin_login", next=request.url))

        # Live database check: must exist, is_active == 1, and is_admin == 1
        conn = get_db()
        user = conn.execute("SELECT id, is_admin, is_active FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()

        if not user or user["is_active"] != 1 or user["is_admin"] != 1:
            session["is_admin"] = 0
            flash("Access denied: Active administrator privileges required.")
            return redirect(url_for("home"))

        return view(**kwargs)
    return wrapped_view


def create_notification(user_id, title, message, notification_type, related_item_id=None):
    """Helper to record a persistent student notification."""
    if not user_id:
        return
    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO notifications (user_id, title, message, notification_type, related_item_id, is_read)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (user_id, title, message, notification_type, related_item_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Notification error: {e}")


# -------------------------------------------------------------
# Home & Item Browsing
# -------------------------------------------------------------

@app.route("/")
def home():
    q = request.args.get("q", "").strip()
    report_type = request.args.get("type", "").strip()
    category = request.args.get("category", "").strip()

    # Omit archived items from public view
    query = "SELECT * FROM items WHERE (is_archived = 0 OR is_archived IS NULL)"
    params = []

    if q:
        query += " AND (LOWER(name) LIKE ? OR LOWER(description) LIKE ?)"
        params.extend([f"%{q.lower()}%", f"%{q.lower()}%"])

    if report_type in ("lost", "found"):
        query += " AND report_type = ?"
        params.append(report_type)

    if category:
        query += " AND category = ?"
        params.append(category)

    query += " ORDER BY id DESC"

    conn = get_db()
    items = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "index.html",
        items=items,
        search_query=q,
        filter_type=report_type,
        filter_category=category
    )


@app.route("/item/<int:item_id>")
def item_detail(item_id):
    conn = get_db()
    item = conn.execute("""
        SELECT i.*, u.name as reporter_name
        FROM items i
        LEFT JOIN users u ON i.user_id = u.id
        WHERE i.id = ?
    """, (item_id,)).fetchone()

    # Check if current user has already claimed this item
    user_claim = None
    if item and "user_id" in session:
        user_claim = conn.execute(
            "SELECT * FROM claims WHERE item_id = ? AND claimant_id = ?",
            (item_id, session["user_id"])
        ).fetchone()

    conn.close()

    if item is None:
        abort(404)

    return render_template("detail.html", item=item, user_claim=user_claim)


# -------------------------------------------------------------
# Reporting Items
# -------------------------------------------------------------

@app.route("/report/<report_type>", methods=["GET", "POST"])
def report_item(report_type):

    if report_type not in ["lost", "found"]:
        return "Invalid report type", 404

    if request.method == "POST":
        verify_csrf()

        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        location = request.form.get("location", "").strip()
        item_date = request.form.get("item_date", "").strip()
        email = request.form.get("email", "").strip().lower()

        if not all([name, category, description, location, item_date, email]):
            flash("Please fill in all required fields.")
            return redirect(url_for("report_item", report_type=report_type))

        # Input sanitization and bounds
        if len(name) > 100:
            flash("Item name must be 100 characters or fewer.")
            return redirect(url_for("report_item", report_type=report_type))

        if category not in VALID_CATEGORIES:
            flash("Please select a valid item category.")
            return redirect(url_for("report_item", report_type=report_type))

        if len(description) > 2000:
            flash("Description must be 2,000 characters or fewer.")
            return redirect(url_for("report_item", report_type=report_type))

        if len(location) > 150:
            flash("Location must be 150 characters or fewer.")
            return redirect(url_for("report_item", report_type=report_type))

        if not is_valid_email(email):
            flash("Please provide a valid email address (e.g. name@college.edu).")
            return redirect(url_for("report_item", report_type=report_type))

        photo = request.files.get("photo")
        photo_name = None

        if photo and photo.filename:
            if not is_allowed_image(photo):
                flash("Invalid file. Only genuine image files (JPEG, PNG, GIF, WEBP) under 5 MB are allowed.")
                return redirect(url_for("report_item", report_type=report_type))

            clean_name = secure_filename(photo.filename)
            ext = clean_name.rsplit(".", 1)[1].lower() if "." in clean_name else "jpg"
            photo_name = f"{int(time.time())}_{secrets.token_hex(4)}.{ext}"
            photo.save(os.path.join(UPLOAD_FOLDER, photo_name))

        user_id = session.get("user_id")

        conn = get_db()
        conn.execute("""
            INSERT INTO items
            (name, category, report_type, description,
             location, item_date, email, photo, user_id, is_archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            name, category, report_type, description,
            location, item_date, email, photo_name, user_id
        ))

        conn.commit()
        conn.close()

        flash("Your item report has been submitted successfully!")
        return redirect(url_for("home"))

    default_email = session.get("user_email", "")
    return render_template(
        "report.html",
        report_type=report_type,
        today=date.today().isoformat(),
        default_email=default_email
    )


# -------------------------------------------------------------
# User Authentication (Phase 3)
# -------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour")
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        verify_csrf()

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not all([name, email, password, confirm_password]):
            flash("All fields are required.")
            return render_template("register.html", name=name, email=email)

        if len(name) > 100:
            flash("Full name must be 100 characters or fewer.")
            return render_template("register.html", name=name, email=email)

        if not is_valid_email(email):
            flash("Please enter a valid college email address.")
            return render_template("register.html", name=name, email=email)

        if len(password) < 6 or len(password) > 128:
            flash("Password must be between 6 and 128 characters long.")
            return render_template("register.html", name=name, email=email)

        if password != confirm_password:
            flash("Passwords do not match.")
            return render_template("register.html", name=name, email=email)

        conn = get_db()
        existing_user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()

        if existing_user:
            conn.close()
            flash("An account with this email already exists. Please log in.")
            return redirect(url_for("login"))

        password_hash = generate_password_hash(password)

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, is_admin, is_active) VALUES (?, ?, ?, 0, 1)",
            (name, email, password_hash)
        )
        user_id = cursor.lastrowid

        # Also associate any previously submitted items matching this email
        conn.execute("UPDATE items SET user_id = ? WHERE email = ? AND user_id IS NULL", (user_id, email))

        conn.commit()
        conn.close()

        # Prevent session fixation
        session.clear()
        session["user_id"] = user_id
        session["user_name"] = name
        session["user_email"] = email
        session["is_admin"] = 0
        session["csrf_token"] = secrets.token_hex(16)

        # Welcome notification
        create_notification(
            user_id=user_id,
            title="Welcome to CampusFind! 👋",
            message="Your student account has been created. You can now report items, submit ownership claims, and receive status updates here.",
            notification_type="welcome"
        )

        flash(f"Welcome to CampusFind, {name}! Your account has been created.")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour")
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    next_url = request.args.get("next") or request.form.get("next")

    if request.method == "POST":
        verify_csrf()

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.")
            return render_template("login.html", email=email, next=next_url)

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password. Please try again.")
            return render_template("login.html", email=email, next=next_url)

        # Deactivated account guard
        if "is_active" in user.keys() and user["is_active"] == 0:
            flash("Your account has been deactivated. Please contact campus administration.")
            return render_template("login.html", email=email, next=next_url)

        # Prevent session fixation
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        session["is_admin"] = user["is_admin"] if "is_admin" in user.keys() else 0
        session["csrf_token"] = secrets.token_hex(16)

        flash(f"Welcome back, {user['name']}!")

        safe_next = next_url if is_safe_url(next_url) else None
        if session["is_admin"]:
            return redirect(safe_next or url_for("admin_dashboard"))
        return redirect(safe_next or url_for("dashboard"))

    return render_template("login.html", next=next_url)


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been successfully logged out.")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    user_email = session.get("user_email", "")

    conn = get_db()

    # 1. My reported items
    my_items = conn.execute("""
        SELECT * FROM items
        WHERE (user_id = ? OR email = ?) AND (is_archived = 0 OR is_archived IS NULL)
        ORDER BY id DESC
    """, (user_id, user_email)).fetchall()

    # 2. My submitted claims
    my_claims = conn.execute("""
        SELECT c.*,
               i.name AS item_name,
               i.category AS item_category,
               i.location AS item_location,
               i.photo AS item_photo,
               i.status AS item_status
        FROM claims c
        JOIN items i ON c.item_id = i.id
        WHERE c.claimant_id = ?
        ORDER BY c.id DESC
    """, (user_id,)).fetchall()

    # 3. Incoming claims on items I reported
    incoming_claims = conn.execute("""
        SELECT c.*,
               i.name AS item_name,
               i.photo AS item_photo,
               u.name AS claimant_name,
               u.email AS claimant_email
        FROM claims c
        JOIN items i ON c.item_id = i.id
        JOIN users u ON c.claimant_id = u.id
        WHERE (i.user_id = ? OR i.email = ?)
        ORDER BY c.id DESC
    """, (user_id, user_email)).fetchall()

    # 4. Recent notifications for this user (Phase 5)
    recent_notifications = conn.execute("""
        SELECT n.*, i.name as item_name
        FROM notifications n
        LEFT JOIN items i ON n.related_item_id = i.id
        WHERE n.user_id = ?
        ORDER BY n.id DESC LIMIT 4
    """, (user_id,)).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        my_items=my_items,
        my_claims=my_claims,
        incoming_claims=incoming_claims,
        recent_notifications=recent_notifications
    )


# -------------------------------------------------------------
# Notification System (Phase 5)
# -------------------------------------------------------------

@app.route("/notifications")
@login_required
def notifications_list():
    conn = get_db()
    notifications = conn.execute("""
        SELECT n.*, i.name as item_name
        FROM notifications n
        LEFT JOIN items i ON n.related_item_id = i.id
        WHERE n.user_id = ?
        ORDER BY n.id DESC
    """, (session["user_id"],)).fetchall()
    conn.close()

    return render_template("notifications.html", notifications=notifications)


@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    verify_csrf()
    conn = get_db()
    # Security: Ensure student can only mark their own notification as read
    conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
                 (notification_id, session["user_id"]))
    conn.commit()
    conn.close()

    next_url = request.args.get("next") or request.form.get("next")
    safe_next = next_url if is_safe_url(next_url) else None
    return redirect(safe_next or url_for("notifications_list"))


@app.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_notifications_read():
    verify_csrf()
    conn = get_db()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (session["user_id"],))
    conn.commit()
    conn.close()

    flash("All notifications have been marked as read.")
    return redirect(url_for("notifications_list"))


# -------------------------------------------------------------
# Claim Workflow (Phase 3 & Phase 5 Notifications)
# -------------------------------------------------------------

@app.route("/claim/<int:item_id>", methods=["GET", "POST"])
@login_required
def claim_item(item_id):
    conn = get_db()
    item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()

    if item is None:
        conn.close()
        flash("Item not found.")
        return redirect(url_for("home"))

    if item["report_type"] != "found":
        conn.close()
        flash("Claims can only be submitted for Found items.")
        return redirect(url_for("item_detail", item_id=item_id))

    user_id = session["user_id"]
    user_email = session.get("user_email", "").lower()

    # Rule: Prevent users from claiming their own reports
    if item["user_id"] == user_id or item["email"].lower() == user_email:
        conn.close()
        flash("You cannot claim an item you reported yourself.")
        return redirect(url_for("item_detail", item_id=item_id))

    # Check for existing claim by this user
    existing_claim = conn.execute("""
        SELECT id, status FROM claims
        WHERE item_id = ? AND claimant_id = ?
    """, (item_id, user_id)).fetchone()

    if existing_claim:
        conn.close()
        flash(f"You have already submitted a claim for this item (Status: {existing_claim['status']}).")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        verify_csrf()
        claim_reason = request.form.get("claim_reason", "").strip()
        contact_info = request.form.get("contact_info", "").strip()

        if not claim_reason or not contact_info:
            conn.close()
            flash("Please provide both proof of ownership and your contact info.")
            return render_template("claim.html", item=item, claim_reason=claim_reason, contact_info=contact_info)

        if len(claim_reason) > 2000:
            conn.close()
            flash("Claim details must be 2,000 characters or fewer.")
            return render_template("claim.html", item=item, claim_reason=claim_reason, contact_info=contact_info)

        if len(contact_info) > 200:
            conn.close()
            flash("Contact information must be 200 characters or fewer.")
            return render_template("claim.html", item=item, claim_reason=claim_reason, contact_info=contact_info)

        conn.execute("""
            INSERT INTO claims (item_id, claimant_id, claim_reason, contact_info, status)
            VALUES (?, ?, ?, ?, 'Pending')
        """, (item_id, user_id, claim_reason, contact_info))

        conn.commit()
        conn.close()

        # Notification Trigger: Notify the student who found the item
        if item["user_id"]:
            create_notification(
                user_id=item["user_id"],
                title="New Ownership Claim Received 📥",
                message=f"A student submitted a claim for the found item '{item['name']}'. Review their proof in your Dashboard.",
                notification_type="claim_received",
                related_item_id=item["id"]
            )

        flash("Your claim request has been submitted! You can track its status in your Dashboard.")
        return redirect(url_for("dashboard"))

    conn.close()
    return render_template("claim.html", item=item)


@app.route("/claim/<int:claim_id>/<action>", methods=["POST"])
@login_required
def handle_claim_action(claim_id, action):
    verify_csrf()
    if action not in ["approve", "reject"]:
        flash("Invalid action.")
        return redirect(url_for("dashboard"))

    user_id = session["user_id"]
    user_email = session.get("user_email", "").lower()

    conn = get_db()
    claim = conn.execute("""
        SELECT c.*, i.name as item_name, i.user_id AS item_user_id, i.email AS item_email
        FROM claims c
        JOIN items i ON c.item_id = i.id
        WHERE c.id = ?
    """, (claim_id,)).fetchone()

    if not claim:
        conn.close()
        flash("Claim request not found.")
        return redirect(url_for("dashboard"))

    # Only the owner/reporter of the item can approve or reject claims on it (unless admin)
    if claim["item_user_id"] != user_id and claim["item_email"].lower() != user_email and not session.get("is_admin"):
        conn.close()
        flash("You are not authorized to manage claims for this item.")
        return redirect(url_for("dashboard"))

    new_status = "Approved" if action == "approve" else "Rejected"

    # Fetch conflicting pending claimants before rejecting
    conflicting_claimants = []
    if action == "approve":
        conflicting = conn.execute("""
            SELECT claimant_id FROM claims
            WHERE item_id = ? AND id != ? AND status = 'Pending'
        """, (claim["item_id"], claim_id)).fetchall()
        conflicting_claimants = [c["claimant_id"] for c in conflicting]

    conn.execute("UPDATE claims SET status = ? WHERE id = ?", (new_status, claim_id))

    if action == "approve":
        # Mark the item as Resolved
        conn.execute("UPDATE items SET status = 'Resolved' WHERE id = ?", (claim["item_id"],))
        # Reject conflicting pending claims on this item
        conn.execute("""
            UPDATE claims SET status = 'Rejected'
            WHERE item_id = ? AND id != ? AND status = 'Pending'
        """, (claim["item_id"], claim_id))

        conn.commit()
        conn.close()

        # Notification Trigger: Notify the winning claimant
        create_notification(
            user_id=claim["claimant_id"],
            title="Your Claim Was Approved! 🎉",
            message=f"Good news! Your claim for '{claim['item_name']}' has been approved. The item is now marked as Resolved.",
            notification_type="claim_approved",
            related_item_id=claim["item_id"]
        )

        # Notify conflicting claimants
        for cid in conflicting_claimants:
            create_notification(
                user_id=cid,
                title="Claim Update",
                message=f"Another claim for '{claim['item_name']}' was approved, so your pending claim has been closed.",
                notification_type="claim_rejected",
                related_item_id=claim["item_id"]
            )

        flash("Claim approved! The item has been marked as Resolved.")
    else:
        conn.commit()
        conn.close()

        # Notification Trigger: Notify the rejected claimant
        create_notification(
            user_id=claim["claimant_id"],
            title="Claim Rejected ✖",
            message=f"Your claim for '{claim['item_name']}' was reviewed and rejected.",
            notification_type="claim_rejected",
            related_item_id=claim["item_id"]
        )

        flash("Claim has been rejected.")

    return redirect(url_for("dashboard"))


# =============================================================
# ADMIN SYSTEM (Phase 4C & 4D)
# =============================================================

@app.route("/admin")
@admin_required
def admin_root():
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour")
def admin_login():
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))

    next_url = request.args.get("next") or request.form.get("next")

    if request.method == "POST":
        verify_csrf()

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both administrator email and password.")
            return render_template("admin/login.html", email=email, next=next_url)

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid administrator credentials.")
            return render_template("admin/login.html", email=email, next=next_url)

        if not user["is_admin"]:
            flash("Access denied: This account does not have administrator privileges.")
            return render_template("admin/login.html", email=email, next=next_url)

        if "is_active" in user.keys() and user["is_active"] == 0:
            flash("Your administrator account has been deactivated.")
            return render_template("admin/login.html", email=email, next=next_url)

        # Prevent session fixation
        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        session["is_admin"] = 1
        session["csrf_token"] = secrets.token_hex(16)

        flash(f"Welcome to the Admin Portal, {user['name']}!")
        safe_next = next_url if is_safe_url(next_url) else None
        return redirect(safe_next or url_for("admin_dashboard"))

    return render_template("admin/login.html", next=next_url)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("You have been logged out of the Administrator Portal.")
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    conn = get_db()

    # Exact Real Statistics
    stats = {
        "total_students": conn.execute("SELECT count(*) FROM users WHERE is_admin = 0").fetchone()[0],
        "total_lost": conn.execute("SELECT count(*) FROM items WHERE report_type = 'lost'").fetchone()[0],
        "total_found": conn.execute("SELECT count(*) FROM items WHERE report_type = 'found'").fetchone()[0],
        "total_items": conn.execute("SELECT count(*) FROM items").fetchone()[0],
        "pending_claims": conn.execute("SELECT count(*) FROM claims WHERE status = 'Pending'").fetchone()[0],
        "approved_claims": conn.execute("SELECT count(*) FROM claims WHERE status = 'Approved'").fetchone()[0],
        "resolved_items": conn.execute("SELECT count(*) FROM items WHERE status = 'Resolved'").fetchone()[0],
        "open_items": conn.execute("SELECT count(*) FROM items WHERE status = 'Open'").fetchone()[0],
    }

    # Recent Activity 1: Recently Registered Students (omit password_hash)
    recent_students = conn.execute("""
        SELECT id, name, email, created_at, is_active, is_admin
        FROM users
        ORDER BY id DESC LIMIT 5
    """).fetchall()

    # Recent Activity 2: Recently Submitted Item Reports
    recent_items = conn.execute("""
        SELECT i.*, u.name as reporter_name
        FROM items i
        LEFT JOIN users u ON i.user_id = u.id
        ORDER BY i.id DESC LIMIT 5
    """).fetchall()

    # Recent Activity 3: Recently Submitted Claims
    recent_claims = conn.execute("""
        SELECT c.*, i.name as item_name, u.name as claimant_name
        FROM claims c
        JOIN items i ON c.item_id = i.id
        JOIN users u ON c.claimant_id = u.id
        ORDER BY c.id DESC LIMIT 5
    """).fetchall()

    conn.close()

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_students=recent_students,
        recent_items=recent_items,
        recent_claims=recent_claims
    )


# -------------------------------------------------------------
# Module 1: Manage Items (/admin/items)
# -------------------------------------------------------------

@app.route("/admin/items")
@admin_required
def admin_items():
    q = request.args.get("q", "").strip()
    report_type = request.args.get("type", "").strip()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()

    query = """
        SELECT i.*, u.name as reporter_name
        FROM items i
        LEFT JOIN users u ON i.user_id = u.id
        WHERE 1=1
    """
    params = []

    if q:
        query += " AND (LOWER(i.name) LIKE ? OR LOWER(i.description) LIKE ? OR LOWER(i.location) LIKE ?)"
        params.extend([f"%{q.lower()}%", f"%{q.lower()}%", f"%{q.lower()}%"])

    if report_type in ("lost", "found"):
        query += " AND i.report_type = ?"
        params.append(report_type)

    if category:
        query += " AND i.category = ?"
        params.append(category)

    if status in ("Open", "Resolved"):
        query += " AND i.status = ?"
        params.append(status)
    elif status == "Archived":
        query += " AND i.is_archived = 1"
    elif status == "Active":
        query += " AND (i.is_archived = 0 OR i.is_archived IS NULL)"

    query += " ORDER BY i.id DESC"

    conn = get_db()
    items = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "admin/items.html",
        items=items,
        search_query=q,
        filter_type=report_type,
        filter_category=category,
        filter_status=status
    )


@app.route("/admin/items/<int:item_id>/status/<new_status>", methods=["POST"])
@admin_required
def admin_item_status(item_id, new_status):
    verify_csrf()
    if new_status not in ["Open", "Resolved"]:
        flash("Invalid status.")
        return redirect(url_for("admin_items"))

    conn = get_db()
    item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    conn.execute("UPDATE items SET status = ? WHERE id = ?", (new_status, item_id))
    conn.commit()
    conn.close()

    if new_status == "Resolved" and item and item["user_id"]:
        create_notification(
            user_id=item["user_id"],
            title="Item Marked Resolved ✅",
            message=f"Your report for '{item['name']}' has been marked as Resolved by the administration.",
            notification_type="item_resolved",
            related_item_id=item["id"]
        )

    flash(f"Item #{item_id} status updated to {new_status}.")
    return redirect(url_for("admin_items"))


@app.route("/admin/items/<int:item_id>/archive", methods=["POST"])
@admin_required
def admin_item_archive(item_id):
    """Soft-delete / archive report so history is never lost."""
    verify_csrf()
    conn = get_db()
    item = conn.execute("SELECT is_archived FROM items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        flash("Item not found.")
        return redirect(url_for("admin_items"))

    new_archived = 0 if item["is_archived"] else 1
    conn.execute("UPDATE items SET is_archived = ? WHERE id = ?", (new_archived, item_id))
    conn.commit()
    conn.close()

    action_text = "archived (hidden from students)" if new_archived else "restored to active"
    flash(f"Item #{item_id} has been {action_text}.")
    return redirect(url_for("admin_items"))


@app.route("/admin/items/<int:item_id>/delete", methods=["POST"])
@admin_required
def admin_item_delete(item_id):
    """Permanent delete with cascaded notification and claim cleanup."""
    verify_csrf()
    conn = get_db()
    conn.execute("DELETE FROM notifications WHERE related_item_id = ?", (item_id,))
    conn.execute("DELETE FROM claims WHERE item_id = ?", (item_id,))
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

    flash(f"Item #{item_id} and associated claims permanently removed.")
    return redirect(url_for("admin_items"))


# -------------------------------------------------------------
# Module 2: Manage Claims (/admin/claims)
# -------------------------------------------------------------

@app.route("/admin/claims")
@admin_required
def admin_claims():
    status = request.args.get("status", "").strip()

    query = """
        SELECT c.*,
               i.name as item_name,
               i.location as item_location,
               i.photo as item_photo,
               u.name as claimant_name,
               u.email as claimant_email,
               rep.name as reporter_name,
               rep.email as reporter_email
        FROM claims c
        JOIN items i ON c.item_id = i.id
        JOIN users u ON c.claimant_id = u.id
        LEFT JOIN users rep ON i.user_id = rep.id
        WHERE 1=1
    """
    params = []

    if status in ("Pending", "Approved", "Rejected"):
        query += " AND c.status = ?"
        params.append(status)

    query += " ORDER BY c.id DESC"

    conn = get_db()
    claims = conn.execute(query, params).fetchall()
    conn.close()

    return render_template("admin/claims.html", claims=claims, filter_status=status)


@app.route("/admin/claims/<int:claim_id>/<action>", methods=["POST"])
@admin_required
def admin_claim_action(claim_id, action):
    verify_csrf()
    if action not in ["approve", "reject"]:
        flash("Invalid action.")
        return redirect(url_for("admin_claims"))

    conn = get_db()
    claim = conn.execute("""
        SELECT c.*, i.name as item_name
        FROM claims c
        JOIN items i ON c.item_id = i.id
        WHERE c.id = ?
    """, (claim_id,)).fetchone()

    if not claim:
        conn.close()
        flash("Claim not found.")
        return redirect(url_for("admin_claims"))

    new_status = "Approved" if action == "approve" else "Rejected"

    conflicting_claimants = []
    if action == "approve":
        conflicting = conn.execute("""
            SELECT claimant_id FROM claims
            WHERE item_id = ? AND id != ? AND status = 'Pending'
        """, (claim["item_id"], claim_id)).fetchall()
        conflicting_claimants = [c["claimant_id"] for c in conflicting]

    conn.execute("UPDATE claims SET status = ? WHERE id = ?", (new_status, claim_id))

    if action == "approve":
        conn.execute("UPDATE items SET status = 'Resolved' WHERE id = ?", (claim["item_id"],))
        conn.execute("""
            UPDATE claims SET status = 'Rejected'
            WHERE item_id = ? AND id != ? AND status = 'Pending'
        """, (claim["item_id"], claim_id))
        conn.commit()
        conn.close()

        # Notification Trigger
        create_notification(
            user_id=claim["claimant_id"],
            title="Claim Approved by Administrator! 🎉",
            message=f"Your claim for '{claim['item_name']}' was approved by campus administration. Item is marked Resolved.",
            notification_type="claim_approved",
            related_item_id=claim["item_id"]
        )

        for cid in conflicting_claimants:
            create_notification(
                user_id=cid,
                title="Claim Update",
                message=f"Another claim for '{claim['item_name']}' was approved, and your pending claim was closed.",
                notification_type="claim_rejected",
                related_item_id=claim["item_id"]
            )

        flash(f"Claim #{claim_id} approved. Item marked Resolved and conflicting claims rejected.")
    else:
        conn.commit()
        conn.close()

        create_notification(
            user_id=claim["claimant_id"],
            title="Claim Rejected by Administrator ✖",
            message=f"Your claim for '{claim['item_name']}' was reviewed and rejected by the administration.",
            notification_type="claim_rejected",
            related_item_id=claim["item_id"]
        )

        flash(f"Claim #{claim_id} rejected.")

    return redirect(url_for("admin_claims"))


# -------------------------------------------------------------
# Module 3: Manage Students (/admin/users)
# -------------------------------------------------------------

@app.route("/admin/users")
@admin_required
def admin_users():
    q = request.args.get("q", "").strip()

    query = """
        SELECT u.id, u.name, u.email, u.created_at, u.is_admin, u.is_active,
               (SELECT count(*) FROM items WHERE user_id = u.id) as item_count,
               (SELECT count(*) FROM claims WHERE claimant_id = u.id) as claim_count
        FROM users u
        WHERE 1=1
    """
    params = []

    if q:
        query += " AND (LOWER(u.name) LIKE ? OR LOWER(u.email) LIKE ?)"
        params.extend([f"%{q.lower()}%", f"%{q.lower()}%"])

    query += " ORDER BY u.id DESC"

    conn = get_db()
    users = conn.execute(query, params).fetchall()
    conn.close()

    return render_template("admin/users.html", users=users, search_query=q)


@app.route("/admin/users/<int:user_id>")
@admin_required
def admin_user_detail(user_id):
    """View detailed student activity, submitted reports, and claims."""
    conn = get_db()
    user = conn.execute("""
        SELECT id, name, email, created_at, is_admin, is_active
        FROM users WHERE id = ?
    """, (user_id,)).fetchone()

    if not user:
        conn.close()
        flash("Student account not found.")
        return redirect(url_for("admin_users"))

    user_items = conn.execute("SELECT * FROM items WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    user_claims = conn.execute("""
        SELECT c.*, i.name as item_name, i.location as item_location
        FROM claims c
        JOIN items i ON c.item_id = i.id
        WHERE c.claimant_id = ?
        ORDER BY c.id DESC
    """, (user_id,)).fetchall()

    conn.close()
    return render_template("admin/user_detail.html", user=user, user_items=user_items, user_claims=user_claims)


@app.route("/admin/users/<int:user_id>/toggle-status", methods=["POST"])
@admin_required
def admin_toggle_user_status(user_id):
    verify_csrf()
    if user_id == session.get("user_id"):
        flash("Security alert: You cannot deactivate your own account.")
        return redirect(url_for("admin_users"))

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    if not user:
        conn.close()
        flash("User not found.")
        return redirect(url_for("admin_users"))

    new_status = 0 if user["is_active"] else 1
    conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, user_id))
    conn.commit()
    conn.close()

    status_str = "activated" if new_status else "deactivated"
    flash(f"Student '{user['name']}' ({user['email']}) has been {status_str}.")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/toggle-admin", methods=["POST"])
@admin_required
def admin_toggle_role(user_id):
    verify_csrf()
    if user_id == session.get("user_id"):
        flash("Security alert: You cannot demote your own administrator account.")
        return redirect(url_for("admin_users"))

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    if not user:
        conn.close()
        flash("User not found.")
        return redirect(url_for("admin_users"))

    new_role = 0 if user["is_admin"] else 1
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_role, user_id))
    conn.commit()
    conn.close()

    role_text = "Administrator" if new_role else "Student"
    flash(f"User '{user['name']}' role changed to {role_text}.")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_user_delete(user_id):
    verify_csrf()
    if user_id == session.get("user_id"):
        flash("Security alert: You cannot delete your own administrator account.")
        return redirect(url_for("admin_users"))

    conn = get_db()
    conn.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM claims WHERE claimant_id = ?", (user_id,))
    conn.execute("UPDATE items SET user_id = NULL WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash("Student account has been removed. Associated items were safely unlinked.")
    return redirect(url_for("admin_users"))


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    host = "0.0.0.0" if IS_PRODUCTION else os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=not IS_PRODUCTION)
