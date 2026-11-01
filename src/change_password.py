"""Usage (from project root, venv active):  python src/change_password.py admin@melodycare.my"""
import sys, getpass
sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv()
from database import SessionLocal, User
from auth import hash_password

email = sys.argv[1]
pw = getpass.getpass("New password: ")
if len(pw) < 10 or pw != getpass.getpass("Repeat: "):
    sys.exit("Passwords differ or are shorter than 10 characters.")
db = SessionLocal()
u = db.query(User).filter(User.email == email).first()
if not u:
    sys.exit("User not found")
u.password = hash_password(pw)
db.commit()
print("Password updated for", email)
