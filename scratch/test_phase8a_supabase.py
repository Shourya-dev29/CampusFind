"""
CampusFind Phase 8A - Supabase Storage Integration Test Suite
Verifies:
1. Application starts without Supabase credentials.
2. Local image upload still works without Supabase.
3. Supabase client initializes with valid configuration.
4. Image upload calls the correct bucket.
5. MIME type is supplied.
6. Signed URL generation works.
7. Existing local images are served locally.
8. Missing cloud images are handled safely.
9. Supabase upload failure does not create an invalid database record.
10. Invalid image files are rejected.
11. Existing authentication and CSRF tests still pass.
12. Admin and claim functionality still works.
"""

import os
import sys
import io
import time
import sqlite3
from unittest.mock import patch, MagicMock

# Ensure project root is on PATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app

passed = 0
failed = 0


def check(description, condition):
    global passed, failed
    if condition:
        print(f"  [PASS] {description}")
        passed += 1
    else:
        print(f"  [FAIL] {description}")
        failed += 1


def get_csrf(client, url="/login"):
    res = client.get(url)
    with client.session_transaction() as sess:
        return sess.get("csrf_token")


def run_tests():
    global passed, failed
    print("=" * 65)
    print("Beginning Phase 8A - Supabase Storage Automated Test Suite")
    print("=" * 65)

    client = app.app.test_client()

    # -------------------------------------------------------------
    # 1. Application starts without Supabase credentials
    # -------------------------------------------------------------
    print("\n[Test 1] Application startup without Supabase credentials")
    with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}, clear=False):
        app.SUPABASE_URL = ""
        app.SUPABASE_SERVICE_ROLE_KEY = ""
        app._supabase_client = None

        check("is_supabase_configured() returns False when unconfigured", not app.is_supabase_configured())
        check("get_supabase_client() returns None when unconfigured", app.get_supabase_client() is None)
        res_health = client.get("/health")
        check("/health returns 200 OK without Supabase", res_health.status_code == 200)

    # -------------------------------------------------------------
    # 2. Local image upload still works without Supabase
    # -------------------------------------------------------------
    print("\n[Test 2] Local image upload fallback without Supabase")
    app.SUPABASE_URL = ""
    app.SUPABASE_SERVICE_ROLE_KEY = ""
    app._supabase_client = None

    # Genuine 1x1 PNG bytes: 89 50 4E 47 0D 0A 1A 0A
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    report_csrf = get_csrf(client, "/report/lost")

    res_local_upload = client.post("/report/lost", data={
        "csrf_token": report_csrf,
        "name": "Phase 8A Local Test Umbrella",
        "category": "Other",
        "description": "Black compact umbrella left in library lobby.",
        "location": "Library 2nd Floor",
        "item_date": "2026-11-12",
        "email": "student8a_local@college.edu",
        "photo": (io.BytesIO(png_bytes), "umbrella_test.png")
    }, follow_redirects=True)

    check("Local upload completes with 200 after redirect", res_local_upload.status_code == 200)

    # Verify record in DB and local file existence
    conn = app.get_db()
    test_item = conn.execute("SELECT id, photo FROM items WHERE name = 'Phase 8A Local Test Umbrella'").fetchone()
    check("Item was inserted into database", test_item is not None)
    if test_item and test_item["photo"]:
        local_saved_file = os.path.join(app.UPLOAD_FOLDER, test_item["photo"])
        check("File was saved to local static/uploads/ directory", os.path.exists(local_saved_file))
        # Cleanup
        if os.path.exists(local_saved_file):
            os.remove(local_saved_file)
        conn.execute("DELETE FROM items WHERE id = ?", (test_item["id"],))
        conn.commit()
    conn.close()

    # -------------------------------------------------------------
    # 3. Supabase client initializes with valid configuration
    # -------------------------------------------------------------
    print("\n[Test 3] Supabase client initialization")
    with patch("supabase.create_client") as mock_create_client:
        mock_instance = MagicMock()
        mock_create_client.return_value = mock_instance

        app.SUPABASE_URL = "https://mockproject.supabase.co"
        app.SUPABASE_SERVICE_ROLE_KEY = "mock-service-role-secret-key-12345"
        app.SUPABASE_BUCKET = "campusfind-uploads"
        app._supabase_client = None

        check("is_supabase_configured() returns True with valid config", app.is_supabase_configured())
        retrieved_client = app.get_supabase_client()
        check("get_supabase_client() returns client instance", retrieved_client == mock_instance)
        mock_create_client.assert_called_once_with(
            "https://mockproject.supabase.co",
            "mock-service-role-secret-key-12345"
        )

    # -------------------------------------------------------------
    # 4 & 5. Image upload calls correct bucket & supplies MIME type
    # -------------------------------------------------------------
    print("\n[Test 4 & 5] Cloud image upload & MIME type verification")
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_storage.from_.return_value = mock_bucket
    mock_bucket.upload.return_value = {"Key": "mocked_path"}

    mock_client = MagicMock()
    mock_client.storage = mock_storage
    app._supabase_client = mock_client

    cloud_csrf = get_csrf(client, "/report/found")
    res_cloud_upload = client.post("/report/found", data={
        "csrf_token": cloud_csrf,
        "name": "Phase 8A Cloud Test Calculator",
        "category": "Electronics",
        "description": "Scientific calculator found in science building lab.",
        "location": "Science Hall 101",
        "item_date": "2026-11-12",
        "email": "student8a_cloud@college.edu",
        "photo": (io.BytesIO(png_bytes), "calculator_test.png")
    }, follow_redirects=True)

    check("Cloud upload completes with 200 after redirect", res_cloud_upload.status_code == 200)
    mock_storage.from_.assert_called_with("campusfind-uploads")
    check("Image upload calls 'campusfind-uploads' bucket", mock_storage.from_.called)

    # Verify upload was called with correct MIME type
    upload_kwargs = mock_bucket.upload.call_args[1] if mock_bucket.upload.call_args else {}
    file_opts = upload_kwargs.get("file_options", {})
    check("MIME type 'image/png' is supplied in file_options", file_opts.get("content-type") == "image/png")

    # Verify filename was stored in SQLite
    conn = app.get_db()
    cloud_item = conn.execute("SELECT id, photo FROM items WHERE name = 'Phase 8A Cloud Test Calculator'").fetchone()
    check("Item was inserted into database with photo filename", cloud_item is not None and cloud_item["photo"] is not None)
    if cloud_item:
        cloud_photo_name = cloud_item["photo"]
        conn.execute("DELETE FROM items WHERE id = ?", (cloud_item["id"],))
        conn.commit()
    conn.close()

    # -------------------------------------------------------------
    # 6. Signed URL generation works
    # -------------------------------------------------------------
    print("\n[Test 6] Signed URL generation from private bucket")
    mock_bucket.create_signed_url.return_value = {
        "signedURL": "https://mockproject.supabase.co/storage/v1/object/sign/campusfind-uploads/test_signed.png?token=mocktoken123"
    }

    # Request non-local file
    res_signed = client.get("/static/uploads/test_signed.png")
    check("Route redirects to signed URL (302 Found)", res_signed.status_code == 302)
    check("Redirect location matches Supabase signed URL", "https://mockproject.supabase.co/storage/v1/object/sign/campusfind-uploads/test_signed.png?token=mocktoken123" == res_signed.location)
    mock_bucket.create_signed_url.assert_called_with("test_signed.png", expires_in=3600)

    # -------------------------------------------------------------
    # 7. Existing local images are served locally
    # -------------------------------------------------------------
    print("\n[Test 7] Existing local images served directly without cloud calls")
    mock_bucket.reset_mock()
    res_existing_img = client.get("/static/uploads/WhatsApp_Image_2026-10-30_at_2.59.43_PM.jpeg")
    check("Existing local image returns 200 OK", res_existing_img.status_code == 200)
    check("Image content length matches original (>100KB)", len(res_existing_img.data) > 100000)
    check("Supabase was NOT called for local image", not mock_bucket.create_signed_url.called)

    # -------------------------------------------------------------
    # 8. Missing cloud images are handled safely
    # -------------------------------------------------------------
    print("\n[Test 8] Missing images and Supabase errors handled gracefully")
    mock_bucket.create_signed_url.side_effect = Exception("Object not found in storage bucket")
    res_missing = client.get("/static/uploads/completely_nonexistent_photo_99999.png")
    check("Missing cloud image returns 404 Not Found", res_missing.status_code == 404)
    check("404 page renders friendly error template", b"Page Not Found" in res_missing.data)
    mock_bucket.create_signed_url.side_effect = None

    # -------------------------------------------------------------
    # 9. Supabase upload failure does not create an invalid database record
    # -------------------------------------------------------------
    print("\n[Test 9] Upload failure atomicity (no dangling database records)")
    mock_bucket.upload.side_effect = Exception("Supabase Storage Network Failure")
    app.SUPABASE_FALLBACK_LOCAL = False  # Ensure fallback is off

    fail_csrf = get_csrf(client, "/report/lost")
    res_fail_upload = client.post("/report/lost", data={
        "csrf_token": fail_csrf,
        "name": "Phase 8A Failed Upload Should Not Exist",
        "category": "Wallets",
        "description": "Leather wallet with student ID card.",
        "location": "Cafeteria",
        "item_date": "2026-11-12",
        "email": "student8a_fail@college.edu",
        "photo": (io.BytesIO(png_bytes), "wallet_test.png")
    }, follow_redirects=True)

    check("User is notified of service unavailability", b"Image upload service is currently unavailable" in res_fail_upload.data)
    conn = app.get_db()
    dangling_item = conn.execute("SELECT id FROM items WHERE name = 'Phase 8A Failed Upload Should Not Exist'").fetchone()
    check("No database record was created for the failed upload", dangling_item is None)
    conn.close()
    mock_bucket.upload.side_effect = None

    # -------------------------------------------------------------
    # 10. Invalid image files are rejected
    # -------------------------------------------------------------
    print("\n[Test 10] Image validation & security controls")
    mock_bucket.reset_mock()
    invalid_csrf = get_csrf(client, "/report/lost")

    # Reject text file
    res_txt = client.post("/report/lost", data={
        "csrf_token": invalid_csrf,
        "name": "Invalid File Test",
        "category": "Other",
        "description": "Test description",
        "location": "Campus Center",
        "item_date": "2026-11-12",
        "email": "test@college.edu",
        "photo": (io.BytesIO(b"Hello plain text file"), "malicious.txt")
    }, follow_redirects=True)
    check("Text file upload is rejected", b"Only genuine image files" in res_txt.data)

    # Reject fake PNG with HTML content (magic byte validation)
    res_fake_png = client.post("/report/lost", data={
        "csrf_token": invalid_csrf,
        "name": "Fake PNG Test",
        "category": "Other",
        "description": "Test description",
        "location": "Campus Center",
        "item_date": "2026-11-12",
        "email": "test@college.edu",
        "photo": (io.BytesIO(b"<html><script>alert('xss')</script></html>"), "fake.png")
    }, follow_redirects=True)
    check("Fake PNG with HTML payload is rejected", b"Only genuine image files" in res_fake_png.data)
    check("Supabase upload was NEVER called for invalid files", not mock_bucket.upload.called)

    # -------------------------------------------------------------
    # 11. Existing authentication and CSRF tests still pass
    # -------------------------------------------------------------
    print("\n[Test 11] Auth & CSRF regression verification")
    # Missing CSRF
    res_nocsrf = client.post("/report/lost", data={"name": "No CSRF Item"})
    check("Missing CSRF token returns 400 Bad Request", res_nocsrf.status_code == 400)

    # Register or set valid student session
    with client.session_transaction() as sess:
        sess["user_id"] = 5
        sess["user_name"] = "Shourya Kumar"
        sess["user_email"] = "shourya.singh04@gmail.com"
        sess["is_admin"] = 0

    res_dash = client.get("/dashboard")
    check("Student can access their /dashboard", res_dash.status_code == 200)

    # -------------------------------------------------------------
    # 12. Admin and claim functionality still works
    # -------------------------------------------------------------
    print("\n[Test 12] Admin portal & claims verification")
    # Verify logged-in ordinary student cannot access admin dashboard
    res_student_admin = client.get("/admin/dashboard", follow_redirects=True)
    check("Ordinary student cannot access /admin/dashboard", b"administrator privileges required" in res_student_admin.data.lower())

    # Admin session
    with client.session_transaction() as sess:
        sess["user_id"] = 14
        sess["user_name"] = "Admin Shourya"
        sess["user_email"] = "ijhbg09@gmail.com"
        sess["is_admin"] = 1

    res_admin_dash = client.get("/admin/dashboard")
    check("Admin dashboard returns 200 OK", res_admin_dash.status_code == 200)
    check("Admin items view returns 200 OK", client.get("/admin/items").status_code == 200)
    check("Admin claims view returns 200 OK", client.get("/admin/claims").status_code == 200)

    # Reset Supabase client to clean state
    app.SUPABASE_URL = ""
    app.SUPABASE_SERVICE_ROLE_KEY = ""
    app._supabase_client = None

    print("\n" + "=" * 65)
    print(f"Phase 8A Test Suite Complete: {passed} PASSED, {failed} FAILED")
    print("=" * 65)
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
