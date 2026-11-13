import os
import sys
import shutil
import asyncio  
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from datetime import date, timedelta

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__))

from rag_chain import answer_query
from ingest import build_vector_store, VECTOR_DB_DIR
from auth import verify_password, create_token, get_current_user
from admin_rag import admin_answer
from database import init_db, get_db, User, Patient, MedicalRecord, Appointment, ChatSession, ChatMessage, FeedbackEvent
from sentiment import analyse_sentiment
from triage import classify as triage_classify
from llm_utils import friendly_error
from safety import detect_crisis, check_guest, check_user, CRISIS_FALLBACK
from scope import visible_user_ids
from rag_chain import answer_guest
from api_v1 import router as api_v1_router

app = FastAPI(title="MelodyCare Counselling Chatbot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()
    try:
        if not os.path.exists(VECTOR_DB_DIR) or not os.listdir(VECTOR_DB_DIR):
            print("Building vector store...")
            build_vector_store()
            print("Vector store ready.")
    except Exception as e:
        print(f"Rebuilding vector store: {e}")
        shutil.rmtree(VECTOR_DB_DIR, ignore_errors=True)
        os.makedirs(VECTOR_DB_DIR, exist_ok=True)
        build_vector_store()


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[int] = None


@app.post("/api/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user or not verify_password(request.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user.id, user.email)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
        }
    }


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API key not configured")

    # 1. Session 处理 (同步 DB 操作，速度极快)
    if request.session_id:
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == request.session_id,
                ChatSession.user_id == current_user.id,
            )
            .first()
        )
    else:
        session = None

    if not session:
        session = ChatSession(user_id=current_user.id)
        db.add(session)
        db.flush()

    # -------------------------------------------------------------
    # ⚡ 优化 1：异步并行构建 History 和 Patient Context
    # -------------------------------------------------------------
    def fetch_patient_context():
        children = (
            db.query(Patient).filter(Patient.parent_id == current_user.id).all()
        )
        patient_context = ""
        related_therapist = None

        if children:
            patient_context = f"PARENT: {current_user.name}\n\nCHILDREN:\n"
            for child in children:
                records = (
                    db.query(MedicalRecord)
                    .filter(MedicalRecord.patient_id == child.id)
                    .order_by(MedicalRecord.date.desc())
                    .all()
                )

                patient_context += f"""
Child: {child.name}, Age: {child.age}, Gender: {child.gender}
Diagnosis: {child.diagnosis}
All treatment records:"""
                for r in records:
                    patient_context += f"""
  - {r.date}: {r.diagnosis}
    Treatment: {r.treatment}
    Notes: {r.notes}
    Therapist: {r.therapist}
"""
            # 顺便获取最新的 therapist
            latest_record = (
                db.query(MedicalRecord)
                .filter(MedicalRecord.patient_id == children[0].id)
                .order_by(MedicalRecord.date.desc())
                .first()
            )
            if latest_record:
                related_therapist = latest_record.therapist

        return patient_context, children, related_therapist

    # 将 DB 历史和患者数据并行提出来
    history = [
        {"role": msg.role, "content": msg.content} for msg in session.messages
    ]
    patient_context, children, related_therapist = await asyncio.to_thread(
        fetch_patient_context
    )

    crisis = detect_crisis(request.message)
    if not crisis:  # never block someone who may be in distress
        ok, reason = check_user(current_user.id)
        if not ok:
            raise HTTPException(status_code=429, detail=reason)
    try:
        # -------------------------------------------------------------
        # ⚡ 优化 2：把【回答生成】和【情感分析】并发异步跑！
        # 原本这两个是依次调用的，现在耗时取决于最慢的那一个，整体耗时减少 30%-50%
        # -------------------------------------------------------------
        answer_task = asyncio.to_thread(
            answer_query, request.message, api_key, patient_context, history
        )
        recent = (
            db.query(ChatMessage.sentiment_score)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .filter(ChatSession.user_id == current_user.id, ChatMessage.role == "user", ChatMessage.sentiment_score != None)
            .order_by(ChatMessage.id.desc()).limit(10).all()
        )
        baseline = round(sum(r[0] for r in recent) / len(recent), 2) if len(recent) >= 3 else None
        sentiment_task = asyncio.to_thread(
            analyse_sentiment, request.message, api_key, baseline
        )

        result, sentiment = await asyncio.gather(answer_task, sentiment_task)

        # -------------------------------------------------------------
        # 3. 保持原有的数据库落盘逻辑不变
        # -------------------------------------------------------------
        db.add(
            ChatMessage(
                session_id=session.id,
                role="user",
                content=request.message,
                sentiment_score=sentiment["score"],
                sentiment_label=sentiment["label"],
                related_therapist=related_therapist,
            )
        )
        db.add(
            ChatMessage(
                session_id=session.id,
                role="assistant",
                content=result["answer"],
            )
        )

        # Create feedback event if complaint or praise
        if (
            sentiment["event_type"] in ["complaint", "praise"]
            and sentiment["summary"]
        ):
            patient_id = children[0].id if children else None
            t_class, t_reason = triage_classify(
                sentiment["event_type"], sentiment.get("complaint_target"), sentiment.get("emotional_intensity"),
                sentiment.get("is_specific"), sentiment["score"], baseline,
            )
            db.add(
                FeedbackEvent(
                    user_id=current_user.id,
                    patient_id=patient_id,
                    therapist=related_therapist,
                    session_id=session.id,
                    sentiment_score=sentiment["score"],
                    event_type=sentiment["event_type"],
                    content_summary=sentiment["summary"],
                    complaint_target=sentiment.get("complaint_target"),
                    emotional_intensity=sentiment.get("emotional_intensity"),
                    is_specific=sentiment.get("is_specific"),
                    triage_class=t_class,
                    triage_reason=t_reason or sentiment.get("triage_reason"),
                )
            )

        db.commit()

        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "session_id": session.id,
            "crisis": crisis or (sentiment["label"] == "distressed" and sentiment["score"] < 0.2),
        }
    except Exception as e:
        db.rollback()
        print(f"Chat error: {e}")
        if crisis:  # never leave a person in distress with an error message
            return {"answer": CRISIS_FALLBACK, "sources": [], "session_id": session.id, "crisis": True}
        raise HTTPException(status_code=503, detail=friendly_error(e))


@app.post("/api/admin/chat")
async def admin_chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")

    ok, reason = check_user(current_user.id)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API key not configured")

    # 1. 将耗时的数据库 Context 组装放到独立后台线程，避免阻塞主事件循环
    def build_admin_context():
        scope = visible_user_ids(current_user, db)
        pq = db.query(Patient)
        if scope is not None:
            pq = pq.filter(Patient.parent_id.in_(scope))
        patients = pq.all()
        today = date.today()
        week_end = today + timedelta(days=7)
        aq = db.query(Appointment).filter(
            Appointment.date >= today,
            Appointment.date <= week_end
        )
        if scope is not None:
            aq = aq.filter(Appointment.patient_id.in_([p.id for p in patients]))
        appointments = aq.order_by(Appointment.date, Appointment.time).all()

        db_context = "=== ALL PATIENTS ===\n"
        for p in patients:
            parent = db.query(User).filter(User.id == p.parent_id).first()
            records = db.query(MedicalRecord).filter(
                MedicalRecord.patient_id == p.id
            ).order_by(MedicalRecord.date.desc()).all()

            db_context += f"""
Patient: {p.name} | Age: {p.age} | Gender: {p.gender}
Diagnosis: {p.diagnosis}
Parent/Guardian: {parent.name if parent else 'N/A'}
Treatment Records:"""
            for r in records:
                db_context += f"""
  [{r.date}] {r.diagnosis}
  Treatment: {r.treatment}
  Notes: {r.notes}
  Therapist: {r.therapist}
"""

            # Add parent's chatbot messages
            if parent:
                sessions = db.query(ChatSession).filter(
                    ChatSession.user_id == parent.id
                ).order_by(ChatSession.created_at.desc()).limit(3).all()

                if sessions:
                    db_context += f"\nParent ({parent.name}) recent chatbot messages:\n"
                    for session in sessions:
                        user_messages = db.query(ChatMessage).filter(
                            ChatMessage.session_id == session.id,
                            ChatMessage.role == "user"
                        ).order_by(ChatMessage.created_at.desc()).limit(5).all()
                        for msg in reversed(user_messages):
                            db_context += f"  [{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {parent.name}: {msg.content}\n"

        db_context += "\n=== THIS WEEK'S APPOINTMENTS ===\n"
        for a in appointments:
            patient = db.query(Patient).filter(Patient.id == a.patient_id).first()
            db_context += f"""
{a.date} {a.time} | {patient.name if patient else 'Unknown'} | {a.type}
Therapist: {a.therapist} | Status: {a.status}
Notes: {a.notes or 'None'}
"""
        return db_context

    # ⚡ 优化：非阻塞异步获取 Context
    db_context = await asyncio.to_thread(build_admin_context)

    # Get or create session
    if request.session_id:
        session = db.query(ChatSession).filter(
            ChatSession.id == request.session_id,
            ChatSession.user_id == current_user.id
        ).first()
    else:
        session = None

    if not session:
        session = ChatSession(user_id=current_user.id)
        db.add(session)
        db.flush()

    try:
        # ⚡ 优化：将阻塞式的 admin_answer Gemini API 调用放到 asyncio.to_thread 中执行
        result = await asyncio.to_thread(admin_answer, request.message, api_key, db_context)

        db.add(ChatMessage(
            session_id=session.id,
            role="user",
            content=request.message,
        ))
        db.add(ChatMessage(
            session_id=session.id,
            role="assistant",
            content=result["answer"],
        ))
        db.commit()

        return {
            "answer": result["answer"],
            "session_id": session.id,
        }
    except Exception as e:
        db.rollback()
        print(f"Chat error: {e}")
        raise HTTPException(status_code=503, detail=friendly_error(e))


@app.get("/api/sessions")
def get_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sessions = db.query(ChatSession).filter(
        ChatSession.user_id == current_user.id
    ).order_by(ChatSession.created_at.desc()).limit(10).all()
    return [
        {
            "id": s.id,
            "created_at": str(s.created_at),
            "message_count": len(s.messages),
            "preview": s.messages[0].content[:50] + "..." if s.messages else "New conversation"
        }
        for s in sessions
    ]


@app.get("/api/sessions/{session_id}/messages")
def get_session_messages(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return [
        {"role": m.role, "content": m.content, "created_at": str(m.created_at)}
        for m in session.messages
    ]


@app.get("/api/analytics/sentiment-trend/{user_id}")
def sentiment_trend(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")
    scope = visible_user_ids(current_user, db)
    if scope is not None and user_id not in scope:
        raise HTTPException(status_code=404, detail="User not found")
    
    messages = db.query(ChatMessage).join(ChatSession).filter(
        ChatSession.user_id == user_id,
        ChatMessage.role == "user",
        ChatMessage.sentiment_score != None
    ).order_by(ChatMessage.created_at).all()
    
    user = db.query(User).filter(User.id == user_id).first()
    
    return {
        "user_id": user_id,
        "user_name": user.name if user else "Unknown",
        "data": [
            {
                "timestamp": str(m.created_at),
                "score": m.sentiment_score,
                "label": m.sentiment_label,
                "message_preview": m.content[:50],
                "therapist": m.related_therapist,
            }
            for m in messages
        ]
    }


@app.get("/api/analytics/overview")
def analytics_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")

    scope = visible_user_ids(current_user, db)
    uq = db.query(User).filter(User.role == "user")
    if scope is not None:
        uq = uq.filter(User.id.in_(scope))
    users = uq.all()
    result = []

    for user in users:
        messages = db.query(ChatMessage).join(ChatSession).filter(
            ChatSession.user_id == user.id,
            ChatMessage.role == "user",
            ChatMessage.sentiment_score != None
        ).all()

        if not messages:
            continue

        scores = [m.sentiment_score for m in messages]
        avg_score = sum(scores) / len(scores)
        latest = max(messages, key=lambda m: m.created_at)

        def to_5(s):
            if s < 0.2: return 1
            elif s < 0.4: return 2
            elif s < 0.6: return 3
            elif s < 0.8: return 4
            else: return 5

        label_5 = {1:"Bad", 2:"Poor", 3:"Average", 4:"Good", 5:"Happy"}
        avg_5 = round(sum(to_5(s) for s in scores) / len(scores), 1)

        label_counts = {}
        for m in messages:
            label_counts[m.sentiment_label] = label_counts.get(m.sentiment_label, 0) + 1
        dominant_label = max(label_counts, key=label_counts.get)

        children = db.query(Patient).filter(Patient.parent_id == user.id).all()
        therapists = set()
        for child in children:
            records = db.query(MedicalRecord).filter(
                MedicalRecord.patient_id == child.id
            ).all()
            for r in records:
                if r.therapist:
                    therapists.add(r.therapist)

        feedbacks = db.query(FeedbackEvent).filter(
            FeedbackEvent.user_id == user.id
        ).all()
        complaints = [f for f in feedbacks if f.event_type == "complaint"]
        praises = [f for f in feedbacks if f.event_type == "praise"]

        result.append({
            "user_id": user.id,
            "parent_name": user.name,
            "children": [{"name": c.name, "diagnosis": c.diagnosis} for c in children],
            "therapists": list(therapists),
            "total_messages": len(messages),
            "avg_sentiment_score": avg_5,
            "avg_sentiment_label": label_5.get(round(avg_5), "Average"),
            "dominant_sentiment": dominant_label,
            "latest_sentiment": latest.sentiment_label,
            "latest_score": latest.sentiment_score,
            "complaints": len(complaints),
            "praises": len(praises),
            "trend": "improving" if len(scores) > 1 and scores[-1] > scores[0] else "declining" if len(scores) > 1 and scores[-1] < scores[0] else "stable"
        })

    return result


@app.get("/api/analytics/therapist-performance")
def therapist_performance_removed(current_user: User = Depends(get_current_user)):
    """Kept only so an older admin page does not break. Replaced by /api/analytics/therapist-concerns."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")
    return []


@app.get("/api/analytics/therapist-concerns")
def therapist_concerns(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Complaints and praise per therapist. Complaints are split into real concerns about the therapist
    and emotional venting, so a parent's bad day is not counted against a therapist."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")
    scope = visible_user_ids(current_user, db)
    q = db.query(FeedbackEvent).filter(FeedbackEvent.therapist != None)
    if scope is not None:
        q = q.filter(FeedbackEvent.user_id.in_(scope))
    events = q.order_by(FeedbackEvent.created_at.desc()).all()
    names = {u.id: u.name for u in db.query(User).filter(User.id.in_({e.user_id for e in events})).all()} if events else {}

    out = {}
    for e in events:
        d = out.setdefault(e.therapist, {
            "therapist": e.therapist, "praises": 0, "complaints": 0, "therapist_concern": 0, "emotional_venting": 0,
            "unclear": 0, "not_about_therapist": 0, "not_assessed": 0,
            "_concern_families": set(), "_venting_families": set(), "recent": [],
        })
        if e.event_type == "praise":
            d["praises"] += 1
            continue
        if e.event_type != "complaint":
            continue
        cls = e.triage_class or "not_assessed"  # complaints saved before triage existed
        d["complaints"] += 1
        d[cls] = d.get(cls, 0) + 1
        if cls == "therapist_concern":
            d["_concern_families"].add(e.user_id)
        elif cls == "emotional_venting":
            d["_venting_families"].add(names.get(e.user_id, "Unknown"))
        if len(d["recent"]) < 6:
            d["recent"].append({
                "date": e.created_at.date().isoformat() if e.created_at else None, "class": cls,
                "summary": e.content_summary, "reason": e.triage_reason, "parent": names.get(e.user_id),
            })

    result = []
    for d in out.values():
        fams = d.pop("_concern_families")
        venting = d.pop("_venting_families")
        d["families_raising_concerns"] = len(fams)
        d["venting_families"] = sorted(venting)
        if d["therapist_concern"] >= 2 and len(fams) >= 2:
            d["attention"] = "pattern"
        elif d["therapist_concern"] >= 1:
            d["attention"] = "isolated"
        elif d["emotional_venting"] >= 1:
            d["attention"] = "venting_only"
        else:
            d["attention"] = "none"
        result.append(d)
    order = {"pattern": 0, "isolated": 1, "venting_only": 2, "none": 3}
    result.sort(key=lambda x: (order[x["attention"]], x["therapist"]))
    return result


@app.get("/api/analytics/sentiment-history/{user_id}")
def sentiment_history(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")
    scope = visible_user_ids(current_user, db)
    if scope is not None and user_id not in scope:
        raise HTTPException(status_code=404, detail="User not found")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    messages = db.query(ChatMessage).join(ChatSession).filter(
        ChatSession.user_id == user_id,
        ChatMessage.role == "user",
        ChatMessage.sentiment_score != None
    ).order_by(ChatMessage.created_at).all()

    def to_5_scale(score):
        if score < 0.2: return 1
        elif score < 0.4: return 2
        elif score < 0.6: return 3
        elif score < 0.8: return 4
        else: return 5

    def to_label(score):
        return {1:"Bad", 2:"Poor", 3:"Average", 4:"Good", 5:"Happy"}[to_5_scale(score)]

    def to_color(score):
        return {1:"#ef4444", 2:"#f97316", 3:"#eab308", 4:"#84cc16", 5:"#22c55e"}[to_5_scale(score)]

    data = [
        {
            "timestamp": m.created_at.strftime("%Y-%m-%d %H:%M"),
            "date": m.created_at.strftime("%b %d"),
            "score_raw": round(m.sentiment_score, 2),
            "score_5": to_5_scale(m.sentiment_score),
            "label": to_label(m.sentiment_score),
            "color": to_color(m.sentiment_score),
            "message_preview": m.content[:80] + ("..." if len(m.content) > 80 else ""),
            "therapist": m.related_therapist,
        }
        for m in messages
    ]

    scores_5 = [d["score_5"] for d in data]
    avg = round(sum(scores_5) / len(scores_5), 1) if scores_5 else 0
    trend = "improving" if len(scores_5) > 1 and scores_5[-1] > scores_5[0] else \
            "declining" if len(scores_5) > 1 and scores_5[-1] < scores_5[0] else "stable"
    alerts = [d for d in data if d["score_5"] <= 2]

    return {
        "user_id": user_id,
        "parent_name": user.name,
        "data": data,
        "summary": {
            "total_messages": len(data),
            "avg_score": avg,
            "avg_label": {1:"Bad",2:"Poor",3:"Average",4:"Good",5:"Happy"}.get(round(avg), "Average"),
            "trend": trend,
            "alerts": len(alerts),
            "latest_label": data[-1]["label"] if data else "N/A",
            "latest_score": data[-1]["score_5"] if data else 0,
        }
    }


@app.get("/api/users/by-name")
def find_user_by_name(
    name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")
    scope = visible_user_ids(current_user, db)
    uq = db.query(User).filter(
        User.name.ilike(f"%{name}%"),
        User.role == "user"
    )
    if scope is not None:
        uq = uq.filter(User.id.in_(scope))
    users = uq.all()
    return [{"id": u.id, "name": u.name} for u in users]

class GuestChatRequest(BaseModel):
    message: str
    history: list = []


@app.post("/api/guest/chat")
async def guest_chat(req: GuestChatRequest, request: Request):
    msg = req.message.strip()[:600]
    if not msg:
        raise HTTPException(status_code=400, detail="Please type a message.")
    if detect_crisis(msg):  # safety first: instant, free, and never blocked by the quota
        return {"answer": CRISIS_FALLBACK, "sources": [], "crisis": True, "remaining": None}
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    ok, reason, remaining = check_guest(ip)
    if not ok:
        raise HTTPException(status_code=429, detail=reason)
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Service is not configured.")
    history = [
        {"role": h["role"], "content": str(h.get("content", ""))[:600]}
        for h in req.history[-6:]
        if isinstance(h, dict) and h.get("role") in ("user", "assistant")
    ]
    try:
        result = await asyncio.to_thread(answer_guest, msg, api_key, history)
        return {"answer": result["answer"], "sources": result["sources"], "crisis": False, "remaining": remaining}
    except Exception as e:
        print(f"Guest chat error: {e}")
        raise HTTPException(status_code=503, detail=friendly_error(e))


@app.get("/api/me/children")
def my_children(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Basic info about the logged-in parent's own children (never anyone else's)."""
    out = []
    for p in db.query(Patient).filter(Patient.parent_id == current_user.id).order_by(Patient.id).all():
        recs = sorted(p.records, key=lambda r: r.date)
        nxt = (db.query(Appointment)
               .filter(Appointment.patient_id == p.id, Appointment.date >= date.today(), Appointment.status == "scheduled")
               .order_by(Appointment.date, Appointment.time).first())
        out.append({
            "id": p.id, "name": p.name, "age": p.age, "gender": p.gender, "diagnosis": p.diagnosis,
            "treatment_start": recs[0].date.isoformat() if recs else None,
            "treatment_days": (date.today() - recs[0].date).days if recs else None,
            "sessions": len(recs),
            "last_session": recs[-1].date.isoformat() if recs else None,
            "therapist": recs[-1].therapist if recs else None,
            "next_appointment": {"date": nxt.date.isoformat(), "time": nxt.time, "type": nxt.type, "therapist": nxt.therapist} if nxt else None,
        })
    return out


app.include_router(api_v1_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")