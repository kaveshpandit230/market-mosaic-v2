"""
Run this to grant admin access to a user account.
Usage: python make_admin.py your@email.com
"""
import sys, sqlite3, os

if len(sys.argv) < 2:
    print("Usage: python make_admin.py your@email.com")
    sys.exit(1)

email = sys.argv[1]
db_path = os.path.join(os.path.dirname(__file__), 'market_mosaic.db')

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}. Run the app once first to create it.")
    sys.exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.execute("UPDATE users SET is_admin=1 WHERE email=?", (email,))
conn.commit()

if cursor.rowcount:
    print(f"✓ Admin access granted to {email}")
else:
    print(f"✗ No user found with email: {email}")
conn.close()
