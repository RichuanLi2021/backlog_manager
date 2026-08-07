"""Print where the local database lives and what is inside it."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import DATABASE_URL  # noqa: E402

path = Path(DATABASE_URL.replace("sqlite:///", ""))
print(f"file        : {path}")
print(f"exists      : {path.exists()}  ({path.stat().st_size / 1024:,.0f} KB)")

conn = sqlite3.connect(path)
print(f"sqlite      : {sqlite3.sqlite_version}")
print(f"journal mode: {conn.execute('pragma journal_mode').fetchone()[0]}")
print("tables:")
names = [r[0] for r in conn.execute("select name from sqlite_master where type = 'table'")]
for name in sorted(names):
    count = conn.execute(f"select count(*) from {name}").fetchone()[0]
    print(f"  {name:20} {count:>6} rows")
