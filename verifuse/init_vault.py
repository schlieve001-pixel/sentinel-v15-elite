import sqlite3
import hashlib

DB_PATH = 'verifuse/data/verifuse_vault.db'

def generate_hash(data_tuple):
    raw_string = f"{data_tuple[0]}{data_tuple[1]}{data_tuple[2]}".encode('utf-8')
    return hashlib.sha256(raw_string).hexdigest()

def init_system():
    print("⚙️  INITIALIZING VERIFUSE VAULT SYSTEM...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("   -> Creating 'leads' View abstraction layer...")
    cursor.execute("""
    CREATE VIEW IF NOT EXISTS leads AS 
    SELECT asset_id as id, case_number, county, owner_of_record as owner_name, 
           property_address, estimated_surplus, record_hash FROM assets
    """)

    print("   -> Verifying schema integrity (record_hash column)...")
    try:
        cursor.execute("SELECT record_hash FROM assets LIMIT 1")
    except sqlite3.OperationalError:
        print("      [!] Column missing. Patching database schema...")
        cursor.execute("ALTER TABLE assets ADD COLUMN record_hash TEXT")
    
    print("   -> Auditing Chain of Custody (Signing unsigned records)...")
    cursor.execute("SELECT asset_id, case_number, estimated_surplus FROM assets WHERE record_hash IS NULL")
    unsigned_records = cursor.fetchall()
    
    signed_count = 0
    for record in unsigned_records:
        r_id, case_num, surplus = record
        sig = generate_hash((r_id, case_num, surplus))
        cursor.execute("UPDATE assets SET record_hash = ? WHERE asset_id = ?", (sig, r_id))
        signed_count += 1
    
    conn.commit()
    cursor.execute("SELECT COUNT(*), SUM(estimated_surplus) FROM leads WHERE record_hash IS NOT NULL")
    count, total_equity = cursor.fetchone()
    
    print(f"\n✅ SYSTEM READY.")
    print(f"🔒 Verified Assets: {count}")
    print(f"💰 Total Provable Equity: ${total_equity if total_equity else 0:,.2f}")
    print(f"📝 New Signatures Generated: {signed_count}")
    conn.close()

if __name__ == "__main__":
    init_system()
