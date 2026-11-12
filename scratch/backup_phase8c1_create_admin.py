"""
CampusFind - Secure Admin Account CLI
Allows server administrators to create or promote an admin account safely
without storing or hardcoding passwords in source code or Git.
"""

import sqlite3
import getpass
import os
import sys
import re
from werkzeug.security import generate_password_hash

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def is_valid_email(email):
    if not email or len(email) > 120:
        return False
    return bool(EMAIL_REGEX.match(email))

DATABASE = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "database", "campusfind.db"))

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_admin_column(conn):
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

def secure_input_password(prompt):
    """Hidden password input with fallback for non-tty/piped environments."""
    if not sys.stdin.isatty():
        print(prompt, end="", flush=True)
        return sys.stdin.readline().rstrip("\r\n")
    try:
        return getpass.getpass(prompt)
    except Exception:
        return input(prompt)

def main():
    print("=" * 60)
    print("   CampusFind - Administrator Account Management")
    print("=" * 60)

    if not os.path.exists(DATABASE):
        print(f"Error: Database not found at {DATABASE}")
        print("Please run app.py once first to initialize the database.")
        sys.exit(1)

    conn = get_db()
    init_admin_column(conn)

    email = input("\nEnter Admin Email Address: ").strip().lower()
    if not is_valid_email(email):
        print("Invalid email format (example: admin@college.edu). Aborted.")
        sys.exit(1)

    # Check if user already exists
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if user:
        print(f"\nUser '{user['name']}' ({email}) already exists in the database.")
        if user["is_admin"] == 1:
            print("This user is ALREADY an administrator.")
            change_pw = input("Would you like to reset their password? (y/N): ").strip().lower()
            if change_pw == "y":
                password = secure_input_password("Enter New Password (min 6 chars): ")
                confirm = secure_input_password("Confirm New Password: ")
                if len(password) < 6:
                    print("Password must be at least 6 characters. Aborted.")
                    sys.exit(1)
                if password != confirm:
                    print("Passwords do not match. Aborted.")
                    sys.exit(1)
                pw_hash = generate_password_hash(password)
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user["id"]))
                conn.commit()
                print("Password successfully updated.")
            return

        promote = input("Promote this user to Administrator? (y/N): ").strip().lower()
        if promote == "y":
            conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user["id"],))
            conn.commit()
            print(f"Success: '{user['name']}' has been promoted to Administrator.")
        else:
            print("Operation cancelled.")
        return

    # Create brand new admin user
    name = input("Enter Admin Full Name: ").strip()
    if not name:
        print("Name cannot be empty. Aborted.")
        sys.exit(1)

    password = secure_input_password("Enter Admin Password (min 6 chars): ")
    confirm = secure_input_password("Confirm Admin Password: ")

    if len(password) < 6 or len(password) > 128:
        print("Password must be between 6 and 128 characters. Aborted.")
        sys.exit(1)

    if password != confirm:
        print("Passwords do not match. Aborted.")
        sys.exit(1)

    password_hash = generate_password_hash(password)

    conn.execute(
        "INSERT INTO users (name, email, password_hash, is_admin, is_active) VALUES (?, ?, ?, 1, 1)",
        (name, email, password_hash)
    )
    conn.commit()
    conn.close()

    print("\n" + "=" * 60)
    print(f"Success! Administrator account '{name}' ({email}) has been created.")
    print("You can now log in at: http://127.0.0.1:5000/admin/login")
    print("=" * 60)

if __name__ == "__main__":
    main()
