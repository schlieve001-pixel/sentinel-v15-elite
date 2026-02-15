import os
import sqlite3
import sys

# 1. Load the Canonical DB Path
DB_PATH = os.environ.get("VERIFUSE_DB_PATH")

if not DB_PATH:
    print("CRITICAL ERROR: VERIFUSE_DB_PATH environment variable not set.")
    print("Run: export VERIFUSE_DB_PATH=$(pwd)/verifuse_v2/data/verifuse_v2.db")
    sys.exit(1)

if not os.path.exists(DB_PATH):
    print(f"CRITICAL ERROR: DB file not found at {DB_PATH}")
    sys.exit(1)

print(f"--- MIGRATING DATABASE: {DB_PATH} ---")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 2. Check/Create 'users' table
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
if not cur.fetchone():
    print("Creating 'users' table...")
    cur.execute("""
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        is_verified_attorney INTEGER DEFAULT 0,
        plan_tier TEXT DEFAULT 'RECON',
        unlock_credits INTEGER DEFAULT 0
    );
    """)
else:
    print("'users' table exists. Checking columns...")
    cur.execute("PRAGMA table_info(users);")
    columns = [row[1] for row in cur.fetchall()]
    
    if "plan_tier" not in columns:
        print("Adding 'plan_tier' column...")
        cur.execute("ALTER TABLE users ADD COLUMN plan_tier TEXT DEFAULT 'RECON';")
        
    if "unlock_credits" not in columns:
        print("Adding 'unlock_credits' column...")
        cur.execute("ALTER TABLE users ADD COLUMN unlock_credits INTEGER DEFAULT 0;")

# 3. Check/Create 'lead_unlocks' table
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lead_unlocks';")
if not cur.fetchone():
    print("Creating 'lead_unlocks' table...")
    cur.execute("""
    CREATE TABLE lead_unlocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        lead_id TEXT,
        unlocked_at TEXT,
        plan_tier TEXT,
        UNIQUE(user_id, lead_id)
    );
    """)
else:
    print("'lead_unlocks' table exists.")

# 4. Check/Create 'user_addons' table
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_addons';")
if not cur.fetchone():
    print("Creating 'user_addons' table...")
    cur.execute("""
    CREATE TABLE user_addons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        addon_type TEXT,
        purchased_at TEXT
    );
    """)

conn.commit()
conn.close()
print("--- MIGRATION COMPLETE ---")
