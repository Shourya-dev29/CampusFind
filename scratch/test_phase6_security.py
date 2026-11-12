"""
Phase 6 Comprehensive Security Audit & Remediation Test Suite
Verifies all 14 security audit findings and fixes on CampusFind.
"""
import os
import sys
import io
import sqlite3
import secrets

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import app

def run_security_tests():
    print("=" * 60)
    print("Beginning Phase 6 Security & Hardening Verification")
    print("=" * 60)

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

    # Ensure clean state for test users
    init_conn = sqlite3.connect("database/campusfind.db")
    init_c = init_conn.cursor()
    init_c.execute("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE email = 'sectest_student@college.edu')")
    init_c.execute("DELETE FROM users WHERE email = 'sectest_student@college.edu'")
    init_conn.commit()
    init_conn.close()

    # ---------------------------------------------------------
    # Group 1: Configuration & Security Headers
    # ---------------------------------------------------------
    print("\n[Group 1] Configuration & Defensive HTTP Headers")
    res = client.get("/")
    check("Root page returns 200 OK", res.status_code == 200)
    check("X-Frame-Options: SAMEORIGIN header present", res.headers.get("X-Frame-Options") == "SAMEORIGIN")
    check("X-Content-Type-Options: nosniff header present", res.headers.get("X-Content-Type-Options") == "nosniff")
    check("Referrer-Policy header present", "strict-origin" in res.headers.get("Referrer-Policy", ""))
    check("MAX_CONTENT_LENGTH is set to 5 MB", app.app.config.get("MAX_CONTENT_LENGTH") == 5 * 1024 * 1024)
    check("SESSION_COOKIE_HTTPONLY is True", app.app.config.get("SESSION_COOKIE_HTTPONLY") is True)
    check("SESSION_COOKIE_SAMESITE is Lax", app.app.config.get("SESSION_COOKIE_SAMESITE") == "Lax")

    # ---------------------------------------------------------
    # Group 2: Error Pages & Status Codes
    # ---------------------------------------------------------
    print("\n[Group 2] Semantic HTTP Error Pages")
    res_404 = client.get("/item/999999")
    check("Nonexistent item returns 404 Not Found", res_404.status_code == 404)
    check("404 page renders friendly template", b"Page or Item Not Found" in res_404.data)

    res_page_404 = client.get("/nonexistent-page-url-xyz")
    check("Unknown URL returns 404", res_page_404.status_code == 404)

    # ---------------------------------------------------------
    # Group 3: File Upload Security & Magic Bytes
    # ---------------------------------------------------------
    print("\n[Group 3] File Upload Security & MIME Validation")
    with client.session_transaction() as sess:
        csrf_token = sess["csrf_token"]

    # 3.1 Reject HTML file upload
    html_file = (io.BytesIO(b"<html><script>alert(1)</script></html>"), "exploit.html")
    res_upload_html = client.post("/report/found", data={
        "csrf_token": csrf_token,
        "name": "Found Test Key",
        "category": "Other",
        "description": "Found near gate",
        "location": "Main Gate",
        "item_date": "2026-11-11",
        "email": "finder@college.edu",
        "photo": html_file
    }, follow_redirects=True)
    check("Malicious .html upload is rejected", b"Only genuine image files" in res_upload_html.data)

    # 3.2 Reject SVG file upload
    svg_file = (io.BytesIO(b"<svg><script>alert('xss')</script></svg>"), "vector.svg")
    res_upload_svg = client.post("/report/found", data={
        "csrf_token": csrf_token,
        "name": "Found Test Key",
        "category": "Other",
        "description": "Found near gate",
        "location": "Main Gate",
        "item_date": "2026-11-11",
        "email": "finder@college.edu",
        "photo": svg_file
    }, follow_redirects=True)
    check("SVG upload (potential XSS) is rejected", b"Only genuine image files" in res_upload_svg.data)

    # 3.3 Reject fake PNG (renamed text/executable file without magic bytes)
    fake_png = (io.BytesIO(b"MZ executable header binary content"), "malware.png")
    res_upload_fake = client.post("/report/found", data={
        "csrf_token": csrf_token,
        "name": "Found Test Key",
        "category": "Other",
        "description": "Found near gate",
        "location": "Main Gate",
        "item_date": "2026-11-11",
        "email": "finder@college.edu",
        "photo": fake_png
    }, follow_redirects=True)
    check("Fake PNG with invalid magic bytes is rejected", b"Only genuine image files" in res_upload_fake.data)

    # 3.4 Accept genuine PNG image with real PNG header
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    valid_png = (io.BytesIO(png_bytes), "valid_test_icon.png")
    res_upload_valid = client.post("/report/found", data={
        "csrf_token": csrf_token,
        "name": "Legitimate Blue Umbrella",
        "category": "Other",
        "description": "Found in cafeteria lobby",
        "location": "Cafeteria",
        "item_date": "2026-11-11",
        "email": "legit_finder@college.edu",
        "photo": valid_png
    }, follow_redirects=True)
    check("Genuine PNG image upload succeeds", b"submitted successfully" in res_upload_valid.data)

    # Clean up created test item and uploaded photo
    conn = sqlite3.connect("database/campusfind.db")
    c = conn.cursor()
    c.execute("SELECT photo FROM items WHERE name = 'Legitimate Blue Umbrella'")
    uploaded_row = c.fetchone()
    if uploaded_row and uploaded_row[0]:
        photo_path = os.path.join("static", "uploads", uploaded_row[0])
        if os.path.exists(photo_path):
            os.remove(photo_path)
    c.execute("DELETE FROM items WHERE name = 'Legitimate Blue Umbrella'")
    conn.commit()
    conn.close()

    # 3.5 Reject oversized payload (> 5 MB)
    oversized_data = io.BytesIO(b"A" * (6 * 1024 * 1024))
    res_oversized = client.post("/report/found", data={
        "csrf_token": csrf_token,
        "name": "Big File",
        "category": "Other",
        "description": "Test oversized file",
        "location": "Library",
        "item_date": "2026-11-11",
        "email": "test@college.edu",
        "photo": (oversized_data, "huge.jpg")
    })
    check("Oversized payload (>5MB) triggers 413 Request Entity Too Large", res_oversized.status_code == 413)

    # ---------------------------------------------------------
    # Group 4: CSRF Protection Across All Forms
    # ---------------------------------------------------------
    print("\n[Group 4] CSRF Protection Enforcement")

    # 4.1 Missing CSRF on report submission
    res_no_csrf_report = client.post("/report/found", data={
        "name": "No CSRF item",
        "category": "Other",
        "description": "No CSRF token",
        "location": "Block A",
        "item_date": "2026-11-11",
        "email": "attacker@college.edu"
    })
    check("POST /report/found without CSRF token returns 400 Bad Request", res_no_csrf_report.status_code == 400)

    # 4.2 Missing CSRF on registration
    res_no_csrf_reg = client.post("/register", data={
        "name": "No CSRF User",
        "email": "nocsrf@college.edu",
        "password": "Password123!",
        "confirm_password": "Password123!"
    })
    check("POST /register without CSRF token returns 400 Bad Request", res_no_csrf_reg.status_code == 400)

    # 4.3 Missing CSRF on login
    res_no_csrf_login = client.post("/login", data={
        "email": "nocsrf@college.edu",
        "password": "Password123!"
    })
    check("POST /login without CSRF token returns 400 Bad Request", res_no_csrf_login.status_code == 400)

    # 4.4 Missing CSRF on claim submission (authenticated)
    # Register a valid student first
    client.get("/register")
    with client.session_transaction() as sess:
        sess_token = sess["csrf_token"]

    res_reg_test = client.post("/register", data={
        "csrf_token": sess_token,
        "name": "Security Test Student",
        "email": "sectest_student@college.edu",
        "password": "Password123!",
        "confirm_password": "Password123!"
    }, follow_redirects=True)
    check("Student registration with valid CSRF succeeds", b"Welcome to CampusFind" in res_reg_test.data)

    # Attempt claim without CSRF
    res_no_csrf_claim = client.post("/claim/2", data={
        "claim_reason": "I own this item",
        "contact_info": "555-1234"
    })
    check("POST /claim without CSRF token returns 400 Bad Request", res_no_csrf_claim.status_code == 400)

    # Attempt claim action without CSRF
    res_no_csrf_action = client.post("/claim/1/approve", data={})
    check("POST /claim/<id>/approve without CSRF token returns 400 Bad Request", res_no_csrf_action.status_code == 400)

    # ---------------------------------------------------------
    # Group 5: Open Redirect Protection
    # ---------------------------------------------------------
    print("\n[Group 5] Open Redirect Protection")
    client.get("/logout")
    client.get("/login")  # Trigger ensure_csrf_token()
    with client.session_transaction() as sess:
        login_csrf = sess["csrf_token"]

    # 5.1 External URL in next parameter
    res_redirect_evil = client.post("/login?next=https://attacker-phishing.com", data={
        "csrf_token": login_csrf,
        "email": "sectest_student@college.edu",
        "password": "Password123!"
    })
    check("External redirect next=https://evil.com is blocked", res_redirect_evil.headers.get("Location") == "/dashboard")

    # 5.2 Protocol-relative URL in next parameter
    client.get("/logout")
    client.get("/login")
    with client.session_transaction() as sess:
        login_csrf = sess["csrf_token"]
    res_redirect_proto = client.post("/login?next=//attacker-phishing.com", data={
        "csrf_token": login_csrf,
        "email": "sectest_student@college.edu",
        "password": "Password123!"
    })
    check("Protocol-relative redirect next=//evil.com is blocked", res_redirect_proto.headers.get("Location") == "/dashboard")

    # 5.3 Valid internal URL in next parameter
    client.get("/logout")
    client.get("/login")
    with client.session_transaction() as sess:
        login_csrf = sess["csrf_token"]
    res_redirect_safe = client.post("/login?next=/report/lost", data={
        "csrf_token": login_csrf,
        "email": "sectest_student@college.edu",
        "password": "Password123!"
    })
    check("Safe local redirect next=/report/lost is accepted", res_redirect_safe.headers.get("Location") == "/report/lost")

    # ---------------------------------------------------------
    # Group 6: Live Role & Active Status Database Verification
    # ---------------------------------------------------------
    print("\n[Group 6] Live Database Role & Deactivation Enforcement")

    conn = sqlite3.connect("database/campusfind.db")
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = 'sectest_student@college.edu'")
    sectest_id = c.fetchone()[0]

    # Ordinary student cannot access admin dashboard
    with client.session_transaction() as sess:
        sess["user_id"] = sectest_id
        sess["is_admin"] = 0

    res_admin_access = client.get("/admin/dashboard", follow_redirects=True)
    check("Ordinary student cannot access /admin/dashboard", b"administrator privileges required" in res_admin_access.data.lower())

    # Spoofed cookie: student session has is_admin=1 in cookie, but is_admin=0 in DB
    with client.session_transaction() as sess:
        sess["user_id"] = sectest_id
        sess["is_admin"] = 1  # Forged cookie attribute

    res_admin_forged = client.get("/admin/dashboard", follow_redirects=True)
    check("Forged admin cookie rejected via live DB privilege check", b"Active administrator privileges required" in res_admin_forged.data)

    # Deactivated account check: active session but account is deactivated in DB
    c.execute("UPDATE users SET is_active = 0 WHERE id = ?", (sectest_id,))
    conn.commit()

    with client.session_transaction() as sess:
        sess["user_id"] = sectest_id

    res_deactivated = client.get("/dashboard", follow_redirects=True)
    check("Deactivated user blocked in real-time on /dashboard", b"account has been deactivated" in res_deactivated.data)

    # ---------------------------------------------------------
    # Group 7: SQLite Foreign Key Enforcement
    # ---------------------------------------------------------
    print("\n[Group 7] SQLite Foreign Key Enforcement")
    app_conn = app.get_db()
    fk_status = app_conn.execute("PRAGMA foreign_keys").fetchone()[0]
    app_conn.close()
    check("PRAGMA foreign_keys is ON in application connections", fk_status == 1)

    # ---------------------------------------------------------
    # Group 8: Clean Up & Preservation Check
    # ---------------------------------------------------------
    print("\n[Group 8] Clean Up & Preservation Check")
    c.execute("DELETE FROM notifications WHERE user_id = ?", (sectest_id,))
    c.execute("DELETE FROM users WHERE id = ?", (sectest_id,))
    conn.commit()

    # Verify original records
    c.execute("SELECT count(*) FROM items")
    item_count = c.fetchone()[0]
    check("Original items preserved (count >= 3)", item_count >= 3)

    c.execute("SELECT count(*) FROM users")
    user_count = c.fetchone()[0]
    check("Original user accounts preserved (count >= 2)", user_count >= 2)
    conn.close()

    print("\n" + "=" * 60)
    print(f"Phase 6 Security Verification Complete: {passed}/{total} tests PASSED!")
    print("=" * 60)

if __name__ == "__main__":
    run_security_tests()
