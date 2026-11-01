import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal, init_db, User, Patient, MedicalRecord, Appointment
from auth import hash_password
from datetime import date, timedelta
import secrets


def _pw(env):
    v = os.getenv(env)
    return (v, False) if v else (secrets.token_urlsafe(9), True)


PARENT_PW, PARENT_NEW = _pw("SEED_PARENT_PASSWORD")
ADMIN_PW, ADMIN_NEW = _pw("SEED_ADMIN_PASSWORD")


def seed():
    init_db()
    db = SessionLocal()

    if db.query(User).count() > 0:
        print("Database already seeded.")
        db.close()
        return

    # Dummy parent users
    users = [
        User(name="Sarah Lim", email="sarah@example.com",
             password=hash_password(PARENT_PW), role="user"),
        User(name="Ahmad Razali", email="ahmad@example.com",
             password=hash_password(PARENT_PW), role="user"),
        User(name="Priya Krishnan", email="priya@example.com",
             password=hash_password(PARENT_PW), role="user"),
        User(name="Admin MelodyCare", email="admin@melodycare.my",
             password=hash_password(ADMIN_PW), role="admin"),
    ]
    db.add_all(users)
    db.flush()

    # Dummy children (patients)
    patients = [
        Patient(name="Kay Lim", age=8, gender="Female",
                diagnosis="Anxiety disorder", parent_id=users[0].id),
        Patient(name="Adam Razali", age=10, gender="Male",
                diagnosis="ADHD", parent_id=users[1].id),
        Patient(name="Arya Krishnan", age=7, gender="Female",
                diagnosis="Autism spectrum", parent_id=users[2].id),
    ]
    db.add_all(patients)
    db.flush()

    # Dummy medical records
    records = [
        # Kay Lim - 更丰富的记录
        MedicalRecord(patient_id=patients[0].id, date=date(2026, 3, 5),
                      diagnosis="Initial assessment - Generalised Anxiety",
                      treatment="Psychoeducation for parent, waitlisted for CBT",
                      notes="Kay shows excessive worry about school performance and separation anxiety. Sarah (mother) presented as highly anxious herself, asking many 'what if' questions. Recommend parent to also seek support.",
                      therapist="Dr. Lee Mei Ling"),
        MedicalRecord(patient_id=patients[0].id, date=date(2026, 4, 10),
                      diagnosis="CBT Session 1 - Identifying anxiety triggers",
                      treatment="CBT, breathing exercises introduced",
                      notes="Kay identified school tests and 'not having friends' as main fears. Taught 4-7-8 breathing technique. Sarah reported Kay had a meltdown at school last week. Advised Sarah to remain calm and not reinforce avoidance behaviours.",
                      therapist="Dr. Lee Mei Ling"),
        MedicalRecord(patient_id=patients[0].id, date=date(2026, 5, 10),
                      diagnosis="CBT Session 3 - Behavioural experiments",
                      treatment="Continued CBT, breathing exercises, introduced worry journal",
                      notes="Kay shows improvement in managing school-related anxiety. Mother reports reduced meltdowns at home. Kay successfully attended a school event she had been avoiding. Sarah still tends to over-reassure Kay — discussed how this can maintain anxiety long-term.",
                      therapist="Dr. Lee Mei Ling"),
        MedicalRecord(patient_id=patients[0].id, date=date(2026, 6, 20),
                      diagnosis="CBT Session 5 - Social skills follow-up",
                      treatment="Continued CBT, added social skills group (weekly)",
                      notes="Kay is making friends more easily since joining social skills group. Initiated conversation with a classmate unprompted — significant progress. Sarah (mother) still anxious about Kay's future despite positive signs. Pattern of habitual worry noted — recommend parenting support session to address Sarah's own anxiety style.",
                      therapist="Dr. Lee Mei Ling"),
        MedicalRecord(patient_id=patients[0].id, date=date(2026, 7, 5),
                      diagnosis="Parent consultation - Caregiver anxiety check-in",
                      treatment="Psychoeducation for Sarah on anxiety reinforcement, self-care strategies",
                      notes="Sarah attended alone. Expressed fear that Kay will 'never be normal'. Explored Sarah's own anxiety history — possible GAD traits. Discussed difference between supporting vs overprotecting. Gave Sarah a list of home strategies: (1) praise effort not outcome, (2) allow age-appropriate risk-taking, (3) model calm responses to uncertainty. Sarah found session helpful.",
                      therapist="Dr. Lee Mei Ling"),

        # Adam Razali
        MedicalRecord(patient_id=patients[1].id, date=date(2026, 4, 15),
                      diagnosis="ADHD - moderate, initial assessment",
                      treatment="Behavioural therapy, EDP programme started",
                      notes="Adam struggling with focus in school, impulsive in class. Ahmad (father) showing caregiver fatigue, working long hours and feeling guilty about not spending enough time with Adam.",
                      therapist="Ms. Farah Hana"),
        MedicalRecord(patient_id=patients[1].id, date=date(2026, 6, 10),
                      diagnosis="ADHD follow-up - routine and structure",
                      treatment="Continued behavioural therapy, home routine chart introduced",
                      notes="Adam responds well to structured routine. Teacher reports improvement in staying on task. Ahmad implemented the visual schedule at home — positive results. Remind Ahmad that consistency is key even on weekends.",
                      therapist="Ms. Farah Hana"),

        # Arya Krishnan
        MedicalRecord(patient_id=patients[2].id, date=date(2026, 5, 30),
                      diagnosis="ASD Level 2 - initial assessment",
                      treatment="EDP, social communication therapy started",
                      notes="Arya responding well to structured routine. Priya (mother) in grief stage, needs emotional support. Expressed feeling isolated as none of her friends understand what ASD means.",
                      therapist="Ms. Farah Hana"),
        MedicalRecord(patient_id=patients[2].id, date=date(2026, 7, 1),
                      diagnosis="ASD follow-up - communication progress",
                      treatment="Continued EDP, introduced AAC tools for communication support",
                      notes="Arya used picture cards to express needs at home — breakthrough moment for family. Priya more hopeful but still grieving the gap between Arya and peers. Encouraged Priya to join ASD parent support group. Remind Priya that Arya's progress is real even if it looks different.",
                      therapist="Ms. Farah Hana"),
    ]
    db.add_all(records)
   
    from datetime import date as date_cls
    today = date_cls.today()
    appointments = [
        Appointment(patient_id=patients[0].id, therapist="Dr. Lee Mei Ling",
                    date=today, time="10:00 AM", type="CBT Follow-up",
                    status="scheduled", notes="Discuss Kay's school progress"),
        Appointment(patient_id=patients[1].id, therapist="Ms. Farah Hana",
                    date=today, time="11:30 AM", type="Behavioural Therapy",
                    status="scheduled", notes="Review EDP progress"),
        Appointment(patient_id=patients[2].id, therapist="Dr. Lee Mei Ling",
                    date=today + timedelta(days=1), time="2:00 PM",
                    type="ASD Assessment Follow-up", status="scheduled",
                    notes="Discuss communication therapy outcomes"),
        Appointment(patient_id=patients[0].id, therapist="Ms. Farah Hana",
                    date=today + timedelta(days=2), time="9:00 AM",
                    type="Parenting Support", status="scheduled",
                    notes="Parent emotional check-in for Sarah"),
        Appointment(patient_id=patients[1].id, therapist="Dr. Lee Mei Ling",
                    date=today + timedelta(days=3), time="3:00 PM",
                    type="ADHD Review", status="scheduled",
                    notes="Monthly review with Ahmad"),
    ]
    db.add_all(appointments)
    db.commit()
    db.close()
    print("Seeded: 4 users, 3 patients, 4 medical records.")
    print("\nDemo logins:")
    print("  parents: sarah@example.com, ahmad@example.com, priya@example.com")
    print("  admin  : admin@melodycare.my")
    print("  parent password:", PARENT_PW if PARENT_NEW else "(from SEED_PARENT_PASSWORD)")
    print("  admin password :", ADMIN_PW if ADMIN_NEW else "(from SEED_ADMIN_PASSWORD)")
    print("Write these down now: random passwords are not shown again.")


if __name__ == "__main__":
    seed()