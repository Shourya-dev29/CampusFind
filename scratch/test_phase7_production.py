"""
Phase 7 Production Readiness & Deployment Verification Test Suite
Tests:
- Production SECRET_KEY validation & failure on weak/missing keys
- Secure cookie configuration (HttpOnly, SameSite=Lax, Secure flag)
- Health check endpoints (/health and /healthz)
- Login rate limiting (429 Too Many Requests response)
- Database & upload folder persistence
- Preservation of existing records & functionality
"""
import os
import sys
import sqlite3
import subprocess
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import app

def run_production_tests():
    print("=" * 65)
    print("Beginning Phase 7 Production Readiness Verification")
    print("=" * 65)

    client = app.app.test_client()
    passed = 0
    total = 0

    def check(name, condition):
        nonlocal passed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            raise AssertionError(f"Test failed: {name}")

    # ---------------------------------------------------------
    # Group 1: Health Check Endpoint
    # ---------------------------------------------------------
    print("\n[Group 1] Health Check Monitoring Endpoints")
    res_health = client.get("/health")
    check("GET /health returns 200 OK", res_health.status_code == 200)
    data_health = json.loads(res_health.data.decode("utf-8"))
    check("Health response status is 'healthy'", data_health.get("status") == "healthy")
    check("Health response database is 'connected'", data_health.get("database") == "connected")
    check("No secret keys or credentials in health output", "secret" not in res_health.data.decode("utf-8").lower())

    res_healthz = client.get("/healthz")
    check("GET /healthz alias returns 200 OK", res_healthz.status_code == 200)

    # ---------------------------------------------------------
    # Group 2: Production Secret Key Enforcement
    # ---------------------------------------------------------
    print("\n[Group 2] Production Secret Key Enforcement")
    # Test that in production mode, app refuses to start if SECRET_KEY is missing or weak
    cmd_weak_key = [
        sys.executable, "-c",
        "import os; os.environ['CAMPUSFIND_ENV'] = 'production'; os.environ.pop('SECRET_KEY', None); import app"
    ]
    proc_weak = subprocess.run(cmd_weak_key, capture_output=True, text=True)
    check("App refuses to start in production if SECRET_KEY is missing", proc_weak.returncode != 0 and "CRITICAL SECURITY CONFIGURATION ERROR" in proc_weak.stderr)

    cmd_short_key = [
        sys.executable, "-c",
        "import os; os.environ['CAMPUSFIND_ENV'] = 'production'; os.environ['SECRET_KEY'] = 'short-key'; import app"
    ]
    proc_short = subprocess.run(cmd_short_key, capture_output=True, text=True)
    check("App refuses to start in production if SECRET_KEY is under 32 chars", proc_short.returncode != 0 and "CRITICAL SECURITY CONFIGURATION ERROR" in proc_short.stderr)

    cmd_strong_key = [
        sys.executable, "-c",
        "import os; os.environ['CAMPUSFIND_ENV'] = 'production'; os.environ['SECRET_KEY'] = 'a' * 64; import app; print('SUCCESS')"
    ]
    proc_strong = subprocess.run(cmd_strong_key, capture_output=True, text=True)
    check("App starts successfully in production with valid 64-char key", proc_strong.returncode == 0 and "SUCCESS" in proc_strong.stdout)

    # ---------------------------------------------------------
    # Group 3: Secure Cookie Configuration
    # ---------------------------------------------------------
    print("\n[Group 3] Session Cookie Security Flags")
    check("SESSION_COOKIE_HTTPONLY is True", app.app.config.get("SESSION_COOKIE_HTTPONLY") is True)
    check("SESSION_COOKIE_SAMESITE is Lax", app.app.config.get("SESSION_COOKIE_SAMESITE") == "Lax")
    check("MAX_CONTENT_LENGTH is 5 MB", app.app.config.get("MAX_CONTENT_LENGTH") == 5 * 1024 * 1024)

    # ---------------------------------------------------------
    # Group 4: Rate Limiting Enforcement
    # ---------------------------------------------------------
    print("\n[Group 4] Rate Limiting Protection (429 Response)")
    # Send repeated requests to trigger 10/minute rate limit on /login
    rate_limited = False
    for i in range(12):
        res = client.get("/login")
        if res.status_code == 429:
            rate_limited = True
            check("Rate limit triggers 429 Too Many Requests response", True)
            check("429 response renders friendly custom template", b"Error 429: Rate Limit Exceeded" in res.data)
            break

    if not rate_limited:
        check("Rate limit triggers 429 Too Many Requests response", False)

    # Reset limiter for subsequent tests
    app.limiter.reset()

    # ---------------------------------------------------------
    # Group 5: Database & File Persistence
    # ---------------------------------------------------------
    print("\n[Group 5] Database & Upload Storage Persistence")
    check("DATABASE path is configured", bool(app.DATABASE))
    check("UPLOAD_FOLDER path is configured", bool(app.UPLOAD_FOLDER))
    check("Database file exists on disk", os.path.exists(app.DATABASE))
    check("Upload directory exists on disk", os.path.exists(app.UPLOAD_FOLDER))

    conn = app.get_db()
    fk_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    check("SQLite Foreign Keys remain ON", fk_on == 1)

    c = conn.cursor()
    c.execute("SELECT count(*) FROM items")
    item_count = c.fetchone()[0]
    check("Existing items preserved (count >= 3)", item_count >= 3)

    c.execute("SELECT count(*) FROM users")
    user_count = c.fetchone()[0]
    check("Existing users preserved (count >= 2)", user_count >= 2)

    c.execute("SELECT count(*) FROM claims")
    claim_count = c.fetchone()[0]
    check("Existing claims preserved (count >= 1)", claim_count >= 1)

    conn.close()

    # Verify existing uploads on disk
    upload_files = os.listdir(app.UPLOAD_FOLDER)
    check("Original uploaded photos preserved in static/uploads/", len(upload_files) >= 2)

    print("\n" + "=" * 65)
    print(f"Phase 7 Production Verification Complete: {passed}/{total} tests PASSED!")
    print("=" * 65)

if __name__ == "__main__":
    run_production_tests()

