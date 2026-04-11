"""One-time migration: encrypt plaintext tokens + refresh health data."""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from db import init_db, get_db
from crypto import encrypt, is_encrypted

init_db()
db = get_db()

# 1. Encrypt plaintext tokens
rows = db.execute("SELECT id, token FROM gateways").fetchall()
updated = 0
for row in rows:
    token = row["token"] or ""
    if token and not is_encrypted(token):
        db.execute("UPDATE gateways SET token=? WHERE id=?", (encrypt(token), row["id"]))
        updated += 1
        print(f"  Encrypted: {row['id'][:8]}...")

# 2. Clear stale health caches (version="list" was from old parser)
db.execute("UPDATE gateways SET kind='openclaw' WHERE kind IS NULL OR kind=''")
db.commit()
db.close()

print(f"\nDone: {updated} tokens encrypted, kind normalized")
print("Health will refresh on next GET /api/gateways/")
