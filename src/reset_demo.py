"""Clears chat history and dashboard events of the two demo accounts, so interviewers start clean.
  python src/reset_demo.py            -> dry run (counts only)
  python src/reset_demo.py --apply    -> deletes
Only touches demo.parent@... and demo.admin@...; real accounts are never affected."""
import sys
sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv()
from database import SessionLocal, User, ChatSession, ChatMessage, FeedbackEvent

apply = "--apply" in sys.argv
db = SessionLocal()
ids = [u.id for u in db.query(User).filter(User.email.in_(["demo.parent@melodycare.my", "demo.admin@melodycare.my"])).all()]
if not ids:
    sys.exit("No demo accounts found.")
sess = [s.id for s in db.query(ChatSession).filter(ChatSession.user_id.in_(ids)).all()]
n_msg = db.query(ChatMessage).filter(ChatMessage.session_id.in_(sess)).count() if sess else 0
n_fb = db.query(FeedbackEvent).filter(FeedbackEvent.user_id.in_(ids)).count()
print(f"demo chat sessions: {len(sess)} | messages: {n_msg} | dashboard events: {n_fb}")
if apply:
    db.query(FeedbackEvent).filter(FeedbackEvent.user_id.in_(ids)).delete(synchronize_session=False)
    if sess:
        db.query(ChatMessage).filter(ChatMessage.session_id.in_(sess)).delete(synchronize_session=False)
        db.query(ChatSession).filter(ChatSession.id.in_(sess)).delete(synchronize_session=False)
    db.commit()
    print("Deleted.")
else:
    print("Dry run. Nothing deleted. Run again with --apply.")
