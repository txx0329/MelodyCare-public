"""Creates (or updates) two PUBLIC demo accounts for interviewers, separate from your real admin:
  demo.parent@melodycare.my  (a parent with one synthetic child)
  demo.admin@melodycare.my   (therapist dashboard)
Usage (project root, venv active):  python src/create_demo_accounts.py
Safe to run again: existing demo accounts only get their password updated."""
import sys
from datetime import date, timedelta
sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv()
from database import SessionLocal, User, Patient, MedicalRecord, Appointment
from auth import hash_password

print("These two passwords will be PUBLIC (resume / README), so do not reuse any real password.")
pw_parent = input("Demo parent password (min 8 chars): ").strip()
pw_admin = input("Demo admin password  (min 8 chars): ").strip()
if min(len(pw_parent), len(pw_admin)) < 8:
    sys.exit("Passwords must be at least 8 characters.")

db = SessionLocal()


def upsert_user(name, email, pw, role):
    u = db.query(User).filter(User.email == email).first()
    if u:
        u.password, created = hash_password(pw), False
    else:
        u, created = User(name=name, email=email, password=hash_password(pw), role=role), True
        db.add(u)
    db.commit()
    db.refresh(u)
    return u, created


parent, new_p = upsert_user("Demo Parent", "demo.parent@melodycare.my", pw_parent, "user")
admin, new_a = upsert_user("Demo Admin", "demo.admin@melodycare.my", pw_admin, "admin")

if not db.query(Patient).filter(Patient.parent_id == parent.id).first():
    child = Patient(name="Mia Demo", age=7, gender="Female", diagnosis="Speech and social communication delay (demo data)", parent_id=parent.id)
    db.add(child)
    db.commit()
    db.refresh(child)
    db.add_all([
        MedicalRecord(patient_id=child.id, date=date.today() - timedelta(days=60), diagnosis=child.diagnosis,
                      treatment="Early Development Programme (EDP) started, weekly sessions",
                      notes="Mia responds well to predictable routines and short, clear instructions. Enjoys picture books.",
                      therapist="Ms. Farah Hana"),
        MedicalRecord(patient_id=child.id, date=date.today() - timedelta(days=14), diagnosis=child.diagnosis,
                      treatment="Continued EDP, introduced picture cards for requesting",
                      notes="Starting to use picture cards at home. Still finds group play tiring; keep sessions short.",
                      therapist="Ms. Farah Hana"),
    ])
    db.add(Appointment(patient_id=child.id, therapist="Ms. Farah Hana", date=date.today() + timedelta(days=7),
                       time="10:00", type="EDP session", status="scheduled", notes="Review picture card progress"))
    db.commit()

print(f"\nparent: demo.parent@melodycare.my ({'created' if new_p else 'password updated'})")
print(f"admin : demo.admin@melodycare.my ({'created' if new_a else 'password updated'})")
