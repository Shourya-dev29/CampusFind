"""
CampusFind - Legacy Local Images to Supabase Storage Migration (Phase 8C2)

Safely uploads legacy local item photographs (from static/uploads/) to the private
Supabase Storage bucket ('campusfind-uploads') using their exact filenames.

Safety Features:
- Preserves existing cloud objects without overwriting (upsert=False).
- Detects whether objects already exist in the bucket and skips them.
- Preserves existing local files untouched.
- Supports dry-run inspection (--dry-run).
- Masks credentials and secret keys in output.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app import is_supabase_configured, get_supabase_client, get_image_mime_type, SUPABASE_BUCKET, UPLOAD_FOLDER


def migrate_images(dry_run=False):
    print("=" * 65)
    print("   CampusFind — Legacy Image Migration to Supabase Storage")
    print("=" * 65)

    if not is_supabase_configured():
        print("[-] ERROR: Supabase Storage is not configured.")
        print("[-] Ensure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are set in .env.")
        return False

    if not os.path.exists(UPLOAD_FOLDER):
        print(f"[-] ERROR: Upload directory '{UPLOAD_FOLDER}' does not exist.")
        return False

    client = get_supabase_client()
    if not client:
        print("[-] ERROR: Failed to initialize Supabase client.")
        return False

    # 1. Scan local images
    local_files = [
        f for f in os.listdir(UPLOAD_FOLDER)
        if os.path.isfile(os.path.join(UPLOAD_FOLDER, f)) and not f.startswith(".")
    ]

    print(f"[*] Found {len(local_files)} local image(s) in '{UPLOAD_FOLDER}':")
    for lf in local_files:
        size_kb = os.path.getsize(os.path.join(UPLOAD_FOLDER, lf)) / 1024
        print(f"    - {lf} ({size_kb:.1f} KB)")

    if not local_files:
        print("[+] No local images found to migrate.")
        return True

    # 2. Query existing objects in Supabase bucket to avoid overwrites
    try:
        remote_objects = client.storage.from_(SUPABASE_BUCKET).list()
        remote_filenames = {obj.get("name") for obj in remote_objects if isinstance(obj, dict) and "name" in obj}
        print(f"\n[*] Found {len(remote_filenames)} existing object(s) in cloud bucket '{SUPABASE_BUCKET}'.")
    except Exception as e:
        print(f"[-] Warning: Unable to list remote bucket objects: {e}")
        remote_filenames = set()

    # 3. Process each local file
    to_upload = []
    already_remote = []

    for f in local_files:
        if f in remote_filenames:
            already_remote.append(f)
        else:
            to_upload.append(f)

    if already_remote:
        print("\n[*] The following files already exist in cloud storage (will be preserved as-is):")
        for f in already_remote:
            print(f"    [SKIP] {f}")

    if not to_upload:
        print("\n[+] All local images already exist in Supabase Storage. Nothing to upload.")
        return True

    print(f"\n[*] Images to be uploaded ({len(to_upload)}):")
    for f in to_upload:
        print(f"    [READY] {f}")

    if dry_run:
        print("\n[!] DRY-RUN MODE: Verification complete. No files were uploaded.")
        return True

    # 4. Upload pending images
    print("\n[*] Starting upload to private bucket...")
    uploaded_count = 0

    for f in to_upload:
        filepath = os.path.join(UPLOAD_FOLDER, f)
        ext = f.rsplit(".", 1)[1].lower() if "." in f else "jpg"
        mime_type = get_image_mime_type(ext)

        try:
            with open(filepath, "rb") as img_file:
                file_bytes = img_file.read()

            client.storage.from_(SUPABASE_BUCKET).upload(
                path=f,
                file=file_bytes,
                file_options={"content-type": mime_type, "upsert": "false"}
            )
            print(f"    [OK] Uploaded: {f} ({mime_type})")
            uploaded_count += 1
        except Exception as e:
            print(f"    [FAIL] Error uploading '{f}': {e}")

    print("\n" + "=" * 65)
    print(f"Image Migration Complete: {uploaded_count}/{len(to_upload)} uploaded successfully.")
    print("=" * 65)
    return uploaded_count == len(to_upload)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    success = migrate_images(dry_run=dry)
    sys.exit(0 if success else 1)

