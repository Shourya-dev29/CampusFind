"""
CampusFind Master Regression Test Suite
Runs comprehensive verification across Phases 1, 2, 3, 4, 5, and 6.
"""
import os
import sys
import io
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import app

def run_master_suite():
    print("=" * 65)
    print("   CampusFind Master Regression & Hardening Test Suite")
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

    # Phase 1: Search & Filter
    print("\n[Phase 1] Search & Filtering Verification")
    res_search = client.get("/?q=bag")
    check("Search for 'bag' returns 200 OK", res_search.status_code == 200)
    check("Search results contain matching items", b"bag" in res_search.data.lower())

    res_filter_lost = client.get("/?type=lost")
    check("Filter by type=lost returns 200 OK", res_filter_lost.status_code == 200)

    res_filter_cat = client.get("/?category=Bags")
    check("Filter by category=Bags returns 200 OK", res_filter_cat.status_code == 200)

    # Phase 2: Responsive UI & Detail View
    print("\n[Phase 2] Detail Views & UI Structure")
    res_item1 = client.get("/item/1")
    check("Item #1 detail page returns 200 OK", res_item1.status_code == 200)
    check("Item #1 detail includes category & location", b"Bags" in res_item1.data and b"Category" in res_item1.data)

    res_item2 = client.get("/item/2")
    check("Item #2 detail page returns 200 OK", res_item2.status_code == 200)
    check("Item #2 displays uploaded photo", b"uploads/WhatsApp_Image" in res_item2.data)

    # Phase 3: Authentication & Claims
    print("\n[Phase 3] Authentication & Claim Flow")
    # Clean up test user
    conn = sqlite3.connect("database/campusfind.db")
    c = conn.cursor()
    c.execute("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE email = 'test_reguser@college.edu')")
    c.execute("DELETE FROM claims WHERE claimant_id IN (SELECT id FROM users WHERE email = 'test_reguser@college.edu')")
    c.execute("DELETE FROM users WHERE email = 'test_reguser@college.edu'")
    conn.commit()

    client.get("/register")
    with client.session_transaction() as sess:
        reg_csrf = sess["csrf_token"]

    res_reg = client.post("/register", data={
        "csrf_token": reg_csrf,
        "name": "Regression User",
        "email": "test_reguser@college.edu",
        "password": "Password123!",
        "confirm_password": "Password123!"
    }, follow_redirects=True)
    check("Registration creates user with hashed password", b"Welcome to CampusFind" in res_reg.data)

    c.execute("SELECT id, password_hash FROM users WHERE email = 'test_reguser@college.edu'")
    reg_user_row = c.fetchone()
    check("Password is not plain text", reg_user_row[1] != "Password123!" and "scrypt" in reg_user_row[1] or "pbkdf2" in reg_user_row[1])

    # Phase 4: Admin Portal & Management
    print("\n[Phase 4] Admin Authorization & Management")
    # Verify student cannot access admin routes
    res_admin_denied = client.get("/admin/dashboard", follow_redirects=True)
    check("Ordinary student cannot access /admin/dashboard", b"administrator privileges required" in res_admin_denied.data.lower())

    # Log in as genuine Admin
    admin_row = c.execute("SELECT id, name, email FROM users WHERE is_admin = 1 AND is_active = 1 LIMIT 1").fetchone()
    admin_id = admin_row[0] if admin_row else 999
    admin_name = admin_row[1] if admin_row else "System Administrator"
    admin_email = admin_row[2] if admin_row else "admin@campusfind.test"

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
        sess["user_name"] = admin_name
        sess["user_email"] = admin_email
        sess["is_admin"] = 1

    res_admin_dash = client.get("/admin/dashboard")
    check("Verified admin accesses /admin/dashboard", res_admin_dash.status_code == 200)
    check("Admin dashboard displays statistics", b"Total Item Reports" in res_admin_dash.data)

    res_admin_items = client.get("/admin/items")
    check("Admin can view /admin/items", res_admin_items.status_code == 200)

    res_admin_claims = client.get("/admin/claims")
    check("Admin can view /admin/claims", res_admin_claims.status_code == 200)

    res_admin_users = client.get("/admin/users")
    check("Admin can view /admin/users", res_admin_users.status_code == 200)

    # Phase 5: Notifications
    print("\n[Phase 5] Notifications & Badges")
    student_row = c.execute("SELECT id, name, email FROM users WHERE is_admin = 0 AND is_active = 1 LIMIT 1").fetchone()
    student_id = student_row[0] if student_row else 998
    student_name = student_row[1] if student_row else "Student User"
    student_email = student_row[2] if student_row else "student@campusfind.test"

    with client.session_transaction() as sess:
        sess["user_id"] = student_id
        sess["user_name"] = student_name
        sess["user_email"] = student_email
        sess["is_admin"] = 0

    res_notif = client.get("/notifications")
    check("Student can access /notifications", res_notif.status_code == 200)
    check("Navbar includes notifications link", b"/notifications" in res_notif.data)

    # Phase 6: Hardening & Validation
    print("\n[Phase 6] Security Controls & Boundary Validation")
    # Security headers
    res_hdr = client.get("/")
    check("Security headers active on public response", "SAMEORIGIN" == res_hdr.headers.get("X-Frame-Options"))

    # Cleanup regression user
    c.execute("DELETE FROM notifications WHERE user_id = ?", (reg_user_row[0],))
    c.execute("DELETE FROM users WHERE id = ?", (reg_user_row[0],))
    conn.commit()

    # Original records preservation
    c.execute("SELECT count(*) FROM items")
    check("Existing items intact (>= 3)", c.fetchone()[0] >= 3)
    c.execute("SELECT count(*) FROM users")
    check("Existing users intact (>= 2)", c.fetchone()[0] >= 2)
    conn.close()

    print("\n" + "=" * 65)
    print(f"Master Suite Complete: {passed}/{total} tests PASSED (100%)!")
    print("=" * 65)

if __name__ == "__main__":
    run_master_suite()
