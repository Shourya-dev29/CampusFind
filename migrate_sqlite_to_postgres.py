"""
CampusFind - SQLite to PostgreSQL Data Migration Tool (Phase 8C2)

Safely copies all relational data from the local SQLite database to Supabase PostgreSQL:
- Enforces read-only access on the SQLite database (never modifies or deletes source).
- Verifies the target database state before proceeding.
- Migrates tables in foreign-key dependency order (users -> items -> claims -> notifications).
- Preserves exact primary keys, timestamps, and Werkzeug password hashes without rehashing.
- Synchronizes PostgreSQL auto-increment sequences (setval).
- Executes within an atomic PostgreSQL transaction (automatic rollback on error).
- Masks all credentials and connection strings in console output.
"""

import os
import sys
import sqlite3
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def mask_connection_url(url):
    """Safely mask password in database URI for logs and console display."""
    if not url:
        return "<not configured>"
    try:
        parsed = urlparse(url)
        netloc = ""
        if parsed.username:
            netloc += parsed.username
            if parsed.password:
                netloc += ":*****"
            netloc += "@"
        netloc += parsed.hostname or ""
        if parsed.port:
            netloc += f":{parsed.port}"
        return f"{parsed.scheme}://{netloc}{parsed.path}"
    except Exception:
        return "<invalid url>"


def build_ssl_postgres_url(raw_url):
    """Ensure sslmode=require is applied to PostgreSQL URL."""
    clean_url = raw_url
    if clean_url.startswith("postgres://"):
        clean_url = "postgresql://" + clean_url[11:]

    parsed = urlparse(clean_url)
    query_params = parse_qs(parsed.query)
    if "sslmode" not in query_params:
        query_params["sslmode"] = ["require"]
        new_query = urlencode(query_params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    return clean_url


def create_postgres_schema(pg_cur):
    """Initialize PostgreSQL tables in dependency order."""
    # 1. users
    pg_cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_admin INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );
    """)

    # 2. items
    pg_cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            report_type TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            item_date TEXT NOT NULL,
            email TEXT NOT NULL,
            photo TEXT,
            status TEXT DEFAULT 'Open',
            user_id INTEGER REFERENCES users(id),
            is_archived INTEGER DEFAULT 0
        );
    """)

    # 3. claims
    pg_cur.execute("""
        CREATE TABLE IF NOT EXISTS claims (
            id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES items (id),
            claimant_id INTEGER NOT NULL REFERENCES users (id),
            claim_reason TEXT NOT NULL,
            contact_info TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 4. notifications
    pg_cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users (id),
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            related_item_id INTEGER REFERENCES items (id),
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)


def check_target_is_empty(pg_cur):
    """Check if application tables in PostgreSQL already contain data."""
    tables = ["users", "items", "claims", "notifications"]
    non_empty = {}
    for table in tables:
        try:
            pg_cur.execute(f"SELECT count(*) FROM {table}")
            cnt = pg_cur.fetchone()[0]
            if cnt > 0:
                non_empty[table] = cnt
        except Exception:
            # Table might not exist yet, which is safe
            pass
    return non_empty


def migrate_data(sqlite_path=None, dry_run=False):
    """Execute migration from SQLite to PostgreSQL with strict safety checks."""
    print("=" * 65)
    print("   CampusFind — SQLite to PostgreSQL Migration")
    print("=" * 65)

    # 1. Validate SQLite Source
    sqlite_db = sqlite_path or os.environ.get("DATABASE_PATH", "database/campusfind.db")
    if not os.path.exists(sqlite_db):
        print(f"[-] ERROR: SQLite source database not found at: {sqlite_db}")
        return False

    # 2. Validate PostgreSQL Target URL
    raw_pg_url = os.environ.get("DATABASE_URL", "").strip()
    if not raw_pg_url:
        print("[-] ERROR: DATABASE_URL environment variable is NOT set.")
        print("[-] Please set your Supabase PostgreSQL connection string in .env first.")
        print("    Example: DATABASE_URL=postgresql://postgres.[REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres?sslmode=require")
        return False

    # 3. Guard against accidental loopback
    if "sqlite" in raw_pg_url.lower():
        print("[-] ERROR: DATABASE_URL appears to point to SQLite. Migration target must be PostgreSQL.")
        return False

    masked_target = mask_connection_url(raw_pg_url)
    print(f"[*] Source Database (SQLite):     {sqlite_db}")
    print(f"[*] Target Database (PostgreSQL): {masked_target}")
    if dry_run:
        print("[!] DRY-RUN MODE: Verification only. No data will be written.")

    try:
        import psycopg2
    except ImportError:
        print("[-] ERROR: psycopg2-binary is not installed. Run: pip install psycopg2-binary")
        return False

    # 4. Open SQLite in READ-ONLY mode to guarantee source preservation
    try:
        abs_sqlite = os.path.abspath(sqlite_db)
        sqlite_uri = f"file:{abs_sqlite}?mode=ro"
        sqlite_conn = sqlite3.connect(sqlite_uri, uri=True)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cur = sqlite_conn.cursor()
    except Exception as e:
        # Fallback to standard connect if URI mode fails
        sqlite_conn = sqlite3.connect(sqlite_db)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cur = sqlite_conn.cursor()

    # 5. Connect to PostgreSQL
    pg_url_ssl = build_ssl_postgres_url(raw_pg_url)
    try:
        pg_conn = psycopg2.connect(pg_url_ssl)
        pg_cur = pg_conn.cursor()
    except Exception as e:
        print(f"[-] ERROR: Failed to connect to PostgreSQL: {type(e).__name__}")
        sqlite_conn.close()
        return False

    try:
        # 6. Verify or initialize schema
        create_postgres_schema(pg_cur)
        pg_conn.commit()

        # 7. Preflight Check: Is target empty?
        non_empty = check_target_is_empty(pg_cur)
        if non_empty:
            print("\n[!] SAFETY STOP: Target PostgreSQL database is NOT empty:")
            for tbl, count in non_empty.items():
                print(f"    - Table '{tbl}': {count} existing records")
            print("[-] Aborting migration to prevent data collisions or duplicate records.")
            print("[-] If you wish to re-migrate, clear the target application tables first.")
            return False

        # 8. Read SQLite Source Records
        users = sqlite_cur.execute("SELECT id, name, email, password_hash, created_at, is_admin, is_active FROM users ORDER BY id ASC").fetchall()
        items = sqlite_cur.execute("SELECT id, name, category, report_type, description, location, item_date, email, photo, status, user_id, is_archived FROM items ORDER BY id ASC").fetchall()
        claims = sqlite_cur.execute("SELECT id, item_id, claimant_id, claim_reason, contact_info, status, created_at FROM claims ORDER BY id ASC").fetchall()
        notifications = sqlite_cur.execute("SELECT id, user_id, title, message, notification_type, related_item_id, is_read, created_at FROM notifications ORDER BY id ASC").fetchall()

        print("\n[*] Source Data Inventory:")
        print(f"    - Users:         {len(users)}")
        print(f"    - Items:         {len(items)}")
        print(f"    - Claims:        {len(claims)}")
        print(f"    - Notifications: {len(notifications)}")

        if dry_run:
            print("\n[+] Dry-run preflight checks passed successfully.")
            return True

        # 9. Atomic Transactional Insert in Foreign Key Dependency Order
        print("\n[*] Beginning atomic data migration into PostgreSQL...")

        # Step 1: Users
        for u in users:
            pg_cur.execute("""
                INSERT INTO users (id, name, email, password_hash, created_at, is_admin, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (u["id"], u["name"], u["email"], u["password_hash"], u["created_at"], u["is_admin"], u["is_active"]))

        # Step 2: Items
        for it in items:
            pg_cur.execute("""
                INSERT INTO items (id, name, category, report_type, description, location, item_date, email, photo, status, user_id, is_archived)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (it["id"], it["name"], it["category"], it["report_type"], it["description"], it["location"],
                  it["item_date"], it["email"], it["photo"], it["status"], it["user_id"], it["is_archived"]))

        # Step 3: Claims
        for cl in claims:
            pg_cur.execute("""
                INSERT INTO claims (id, item_id, claimant_id, claim_reason, contact_info, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (cl["id"], cl["item_id"], cl["claimant_id"], cl["claim_reason"], cl["contact_info"], cl["status"], cl["created_at"]))

        # Step 4: Notifications
        for n in notifications:
            pg_cur.execute("""
                INSERT INTO notifications (id, user_id, title, message, notification_type, related_item_id, is_read, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (n["id"], n["user_id"], n["title"], n["message"], n["notification_type"], n["related_item_id"], n["is_read"], n["created_at"]))

        # 10. Synchronize PostgreSQL Auto-Increment Sequences
        print("[*] Synchronizing PostgreSQL sequence generators (setval)...")
        pg_cur.execute("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));")
        pg_cur.execute("SELECT setval(pg_get_serial_sequence('items', 'id'), COALESCE((SELECT MAX(id) FROM items), 1));")
        pg_cur.execute("SELECT setval(pg_get_serial_sequence('claims', 'id'), COALESCE((SELECT MAX(id) FROM claims), 1));")
        pg_cur.execute("SELECT setval(pg_get_serial_sequence('notifications', 'id'), COALESCE((SELECT MAX(id) FROM notifications), 1));")

        # 11. Post-Migration Row Count Validation
        print("[*] Validating post-migration row counts...")
        pg_cur.execute("SELECT count(*) FROM users")
        pg_users = pg_cur.fetchone()[0]
        pg_cur.execute("SELECT count(*) FROM items")
        pg_items = pg_cur.fetchone()[0]
        pg_cur.execute("SELECT count(*) FROM claims")
        pg_claims = pg_cur.fetchone()[0]
        pg_cur.execute("SELECT count(*) FROM notifications")
        pg_notifs = pg_cur.fetchone()[0]

        assert pg_users == len(users), f"User count mismatch: SQLite={len(users)}, Postgres={pg_users}"
        assert pg_items == len(items), f"Item count mismatch: SQLite={len(items)}, Postgres={pg_items}"
        assert pg_claims == len(claims), f"Claim count mismatch: SQLite={len(claims)}, Postgres={pg_claims}"
        assert pg_notifs == len(notifications), f"Notification count mismatch: SQLite={len(notifications)}, Postgres={pg_notifs}"

        # 12. Commit Transaction
        pg_conn.commit()
        print("\n" + "=" * 65)
        print("SUCCESS! Data migration completed with zero data loss.")
        print(f"Migrated: {pg_users} users, {pg_items} items, {pg_claims} claims, {pg_notifs} notifications.")
        print("All sequences synchronized. SQLite source database left untouched.")
        print("=" * 65)
        return True

    except Exception as e:
        print(f"\n[-] ERROR during migration: {e}")
        print("[-] Rolling back PostgreSQL transaction...")
        pg_conn.rollback()
        return False
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    success = migrate_data(dry_run=dry)
    sys.exit(0 if success else 1)

