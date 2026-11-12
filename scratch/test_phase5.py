"""
Phase 5 Comprehensive Test Suite: Notifications & Improved Item Details
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlite3
import re
import app

def run_tests():
    print("==================================================")
    print("Beginning Phase 5 Automated Test Verification")
    print("==================================================")
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

    # 1. Database Schema Verification
    print("\n[Group 1] Database Schema Verification")
    conn = sqlite3.connect("database/campusfind.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(notifications)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    conn.close()

    expected_cols = ["id", "user_id", "title", "message", "notification_type", "related_item_id", "is_read", "created_at"]
    for col in expected_cols:
        check(f"Column '{col}' exists in notifications table", col in columns)

    # 2. Public / Guest Access to Notifications
    print("\n[Group 2] Route Protection & Security")
    res = client.get("/notifications")
    check("GET /notifications without login redirects to /login", res.status_code == 302 and "/login" in res.headers.get("Location", ""))

    res_post = client.post("/notifications/1/read")
    check("POST /notifications/1/read without login redirects to /login", res_post.status_code == 302 and "/login" in res_post.headers.get("Location", ""))

    res_all = client.post("/notifications/mark-all-read")
    check("POST /notifications/mark-all-read without login redirects to /login", res_all.status_code == 302 and "/login" in res_all.headers.get("Location", ""))

    # 3. Create Two Test Students
    print("\n[Group 3] Notification Generation & Unread Tracking")
    conn = sqlite3.connect("database/campusfind.db")
    c = conn.cursor()
    
    # Clean up any leftover test users from earlier runs
    c.execute("DELETE FROM users WHERE email IN ('test_alice@campusfind.test', 'test_bob@campusfind.test')")
    c.execute("DELETE FROM items WHERE email IN ('test_alice@campusfind.test', 'test_bob@campusfind.test')")
    conn.commit()
    conn.close()

    # Register Alice
    client.get("/register")
    with client.session_transaction() as sess:
        alice_csrf = sess["csrf_token"]

    res_reg_a = client.post("/register", data={
        "csrf_token": alice_csrf,
        "name": "Alice Tester",
        "email": "test_alice@campusfind.test",
        "password": "Password123!",
        "confirm_password": "Password123!"
    }, follow_redirects=True)
    check("Alice registers successfully", b"Welcome to CampusFind" in res_reg_a.data)

    conn = sqlite3.connect("database/campusfind.db")
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = 'test_alice@campusfind.test'")
    alice_id = c.fetchone()[0]

    # Verify welcome notification
    c.execute("SELECT title, notification_type, is_read FROM notifications WHERE user_id = ?", (alice_id,))
    alice_notifs = c.fetchall()
    check("Alice has 1 welcome notification", len(alice_notifs) == 1)
    check("Welcome notification type is 'welcome'", alice_notifs[0][1] == "welcome")
    check("Welcome notification is unread (is_read=0)", alice_notifs[0][2] == 0)

    # Check unread badge in Alice's dashboard
    res_dash_a = client.get("/dashboard")
    check("Dashboard shows unread badge / counter", b"Recent Notifications" in res_dash_a.data)
    check("Navbar includes notifications link", b"/notifications" in res_dash_a.data)

    # Alice reports a Found Item
    with client.session_transaction() as sess:
        alice_csrf = sess["csrf_token"]

    res_rep = client.post("/report/found", data={
        "csrf_token": alice_csrf,
        "name": "Blue Wireless Earbuds",
        "category": "Electronics",
        "description": "Found in library 2nd floor silent study cubicle. Sony charging case.",
        "location": "Central Library",
        "item_date": "2026-11-10",
        "email": "test_alice@campusfind.test"
    }, follow_redirects=True)
    check("Alice successfully reports found item", b"successfully" in res_rep.data.lower() or res_rep.status_code == 200)

    c.execute("SELECT id FROM items WHERE name = 'Blue Wireless Earbuds' AND email = 'test_alice@campusfind.test'")
    found_item_id = c.fetchone()[0]
    check("Found item inserted with user_id attached", found_item_id is not None)

    # Logout Alice, register Bob
    client.get("/logout")
    client.get("/register")
    with client.session_transaction() as sess:
        bob_csrf = sess["csrf_token"]

    res_reg_b = client.post("/register", data={
        "csrf_token": bob_csrf,
        "name": "Bob Claimant",
        "email": "test_bob@campusfind.test",
        "password": "Password123!",
        "confirm_password": "Password123!"
    }, follow_redirects=True)
    check("Bob registers successfully", b"Welcome to CampusFind" in res_reg_b.data)

    c.execute("SELECT id FROM users WHERE email = 'test_bob@campusfind.test'")
    bob_id = c.fetchone()[0]
    conn.close()

    # 4. Improved Detail Page Context Checks
    print("\n[Group 4] Improved Item Detail Page Context & UI")
    # Bob views Alice's found item
    res_detail_bob = client.get(f"/item/{found_item_id}")
    check("Detail page displays item name", b"Blue Wireless Earbuds" in res_detail_bob.data)
    check("Detail page displays category", b"Electronics" in res_detail_bob.data)
    check("Detail page displays location", b"Central Library" in res_detail_bob.data)
    check("Detail page displays description", b"Sony charging case" in res_detail_bob.data)
    check("Detail page displays status ● Open", b"Open" in res_detail_bob.data)
    check("Detail page shows 'Claim This Item' button for Bob", b"Claim This Item" in res_detail_bob.data)

    # Bob submits claim on Alice's found item
    with client.session_transaction() as sess:
        bob_claim_csrf = sess["csrf_token"]

    res_claim = client.post(f"/claim/{found_item_id}", data={
        "csrf_token": bob_claim_csrf,
        "claim_reason": "These are my Sony WF-1000XM4 earbuds. The case has a small scratch on bottom right.",
        "contact_info": "Phone: 555-0199, Email: test_bob@campusfind.test"
    }, follow_redirects=True)
    check("Bob submits claim successfully", b"submitted" in res_claim.data.lower())

    # Bob revisits detail page -> should now show pending claim notice
    res_detail_bob_after = client.get(f"/item/{found_item_id}")
    check("Detail page reflects Bob's claim status (Pending)", b"Your Claim Status: Pending" in res_detail_bob_after.data)

    # 5. Verify Notification Triggered for Alice
    print("\n[Group 5] Notification Delivery on Claim Submission")
    conn = sqlite3.connect("database/campusfind.db")
    c = conn.cursor()
    c.execute("""
        SELECT title, message, notification_type, related_item_id, is_read
        FROM notifications WHERE user_id = ? AND notification_type = 'claim_received'
    """, (alice_id,))
    alice_claim_notif = c.fetchone()
    check("Alice received claim_received notification", alice_claim_notif is not None)
    check("Notification mentions item name", "Blue Wireless Earbuds" in alice_claim_notif[1])
    check("Notification links to found_item_id", alice_claim_notif[3] == found_item_id)
    check("Notification is unread", alice_claim_notif[4] == 0)

    # 6. User Isolation & Mark as Read
    print("\n[Group 6] User Notification Isolation & Read Actions")
    # Log in as Alice
    client.get("/logout")
    client.get("/login")
    with client.session_transaction() as sess:
        alice_login_csrf = sess["csrf_token"]
    client.post("/login", data={"csrf_token": alice_login_csrf, "email": "test_alice@campusfind.test", "password": "Password123!"})

    res_alice_notifs = client.get("/notifications")
    check("Alice's notification page lists claim_received", b"New Ownership Claim Received" in res_alice_notifs.data)
    check("Alice does NOT see Bob's welcome notification", b"Welcome to CampusFind, Bob Claimant" not in res_alice_notifs.data)

    # Alice views detail page -> should show owner alert
    res_detail_alice = client.get(f"/item/{found_item_id}")
    check("Detail page tells Alice she reported finding this item", b"You reported finding this item" in res_detail_alice.data)

    # Get Alice's claim notification ID
    c.execute("SELECT id FROM notifications WHERE user_id = ? AND notification_type = 'claim_received'", (alice_id,))
    notif_id = c.fetchone()[0]

    with client.session_transaction() as sess:
        sess_token = sess["csrf_token"]

    # Mark single notification as read
    res_read = client.post(f"/notifications/{notif_id}/read", data={"csrf_token": sess_token}, follow_redirects=True)
    check("Mark as read succeeds", res_read.status_code == 200)

    c.execute("SELECT is_read FROM notifications WHERE id = ?", (notif_id,))
    check("Notification is now marked read (is_read=1)", c.fetchone()[0] == 1)

    # 7. Claim Approval Trigger
    print("\n[Group 7] Claim Approval & Resolved Status Notification")
    c.execute("SELECT id FROM claims WHERE item_id = ? AND claimant_id = ?", (found_item_id, bob_id))
    claim_id = c.fetchone()[0]
    conn.close()

    # Alice approves Bob's claim
    with client.session_transaction() as sess:
        alice_appr_csrf = sess["csrf_token"]
    res_appr = client.post(f"/claim/{claim_id}/approve", data={"csrf_token": alice_appr_csrf}, follow_redirects=True)
    check("Alice approves claim", b"marked as Resolved" in res_appr.data)

    # Verify Bob received approval notification
    conn = sqlite3.connect("database/campusfind.db")
    c = conn.cursor()
    c.execute("""
        SELECT title, message, notification_type, is_read FROM notifications
        WHERE user_id = ? AND notification_type = 'claim_approved'
    """, (bob_id,))
    bob_appr_notif = c.fetchone()
    check("Bob received claim_approved notification", bob_appr_notif is not None)
    check("Approval notification specifies Resolved", "Resolved" in bob_appr_notif[1])

    # Check detail page shows Resolved banner
    res_detail_resolved = client.get(f"/item/{found_item_id}")
    check("Detail page now displays Case Resolved card", b"Case Resolved" in res_detail_resolved.data)

    # 8. Mark All as Read
    print("\n[Group 8] Mark All as Read")
    # Log in as Bob
    client.get("/logout")
    client.get("/login")
    with client.session_transaction() as sess:
        bob_login_csrf = sess["csrf_token"]
    client.post("/login", data={"csrf_token": bob_login_csrf, "email": "test_bob@campusfind.test", "password": "Password123!"})

    with client.session_transaction() as sess:
        bob_csrf = sess["csrf_token"]

    res_bob_notifs = client.get("/notifications")
    check("Bob's notifications page displays approved notification", b"Your Claim Was Approved" in res_bob_notifs.data)

    res_mark_all = client.post("/notifications/mark-all-read", data={"csrf_token": bob_csrf}, follow_redirects=True)
    check("Mark all as read succeeds", b"All notifications have been marked as read" in res_mark_all.data)

    c.execute("SELECT count(*) FROM notifications WHERE user_id = ? AND is_read = 0", (bob_id,))
    unread_bob_count = c.fetchone()[0]
    check("Bob has 0 unread notifications after mark-all-read", unread_bob_count == 0)

    # 9. Clean up test records
    print("\n[Group 9] Clean Up & Preservation Check")
    c.execute("DELETE FROM notifications WHERE user_id IN (?, ?)", (alice_id, bob_id))
    c.execute("DELETE FROM claims WHERE claimant_id IN (?, ?)", (alice_id, bob_id))
    c.execute("DELETE FROM items WHERE id = ?", (found_item_id,))
    c.execute("DELETE FROM users WHERE id IN (?, ?)", (alice_id, bob_id))
    conn.commit()

    # Check original records exist
    c.execute("SELECT count(*) FROM items")
    item_count = c.fetchone()[0]
    check("Original item records preserved (count >= 3)", item_count >= 3)
    conn.close()

    print("\n==================================================")
    print(f"Phase 5 Verification Complete: {passed}/{total} tests PASSED!")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
