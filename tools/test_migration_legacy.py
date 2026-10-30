"""Regression: migrate a pre-fingerprint order_sync_keys SQLite schema without losing receipts.
Run from server/: PYTHONPATH=. python ../tools/test_migration_legacy.py
"""
import os
import sqlite3
import tempfile

data_dir = tempfile.mkdtemp(prefix="pf-legacy-migration-")
os.environ["DATA_DIR"] = data_dir
os.environ["OWNER_PASSWORD"] = "legacy-test-password"
db_path = os.path.join(data_dir, "service.db")

# Emulate the previously deployed table (no payload_sha256).
with sqlite3.connect(db_path) as con:
    con.execute("""
        CREATE TABLE order_sync_keys (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            client_key VARCHAR(80) NOT NULL UNIQUE,
            order_id INTEGER NOT NULL,
            created_at DATETIME
        )
    """)
    con.execute(
        "INSERT INTO order_sync_keys(id,user_id,client_key,order_id,created_at) VALUES(1,7,?,?,?)",
        ("legacy-client-key", 23, "2026-01-01 00:00:00"),
    )

import server

# Exercise the exact production migration sequence.
server.Base.metadata.create_all(server.engine)
server.ensure_columns()
server.ensure_columns()  # migration must be idempotent

with sqlite3.connect(db_path) as con:
    columns = {row[1] for row in con.execute("PRAGMA table_info(order_sync_keys)")}
    assert "payload_sha256" in columns, "migration did not add payload_sha256"
    row = con.execute(
        "SELECT id,user_id,client_key,order_id,payload_sha256 FROM order_sync_keys WHERE id=1"
    ).fetchone()
    assert row == (1, 7, "legacy-client-key", 23, None), f"legacy receipt changed: {row}"
print("OK: legacy receipt preserved; nullable fingerprint added; repeat migration safe")
