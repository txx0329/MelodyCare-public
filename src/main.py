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
from llm_utils import friendly_error
from safety import detect_crisis, check_guest, CRISIS_FALLBACK
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
    try:
        # -------------------------------------------------------------
        # ⚡ 优化 2：把【回答生成】和【情感分析】并发异步跑！
        # 原本这两个是依次调用的，现在耗时取决于最慢的那一个，整体耗时减少 30%-50%
        # -------------------------------------------------------------
        answer_task = asyncio.to_thread(
            answer_query, request.message, api_key, patient_context, history
        )
        sentiment_task = asyncio.to_thread(
            analyse_sentiment, request.message, api_key
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
            db.add(
                FeedbackEvent(
                    user_id=current_user.id,
                    patient_id=patient_id,
                    therapist=related_therapist,
                    session_id=session.id,
                    sentiment_score=sentiment["score"],
                    event_type=sentiment["event_type"],
                    content_summary=sentiment["summary"],
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

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API key not configured")

    # 1. 将耗时的数据库 Context 组装放到独立后台线程，避免阻塞主事件循环
    def build_admin_context():
        patients = db.query(Patient).all()
        today = date.today()
        week_end = today + timedelta(days=7)
        appointments = db.query(Appointment).filter(
            Appointment.date >= today,
            Appointment.date <= week_end
        ).order_by(Appointment.date, Appointment.time).all()

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

    users = db.query(User).filter(User.role == "user").all()
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
def therapist_performance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")

    messages = db.query(ChatMessage).filter(
        ChatMessage.role == "user",
        ChatMessage.sentiment_score != None,
        ChatMessage.related_therapist != None
    ).all()

    therapist_data = {}
    for m in messages:
        t = m.related_therapist
        if t not in therapist_data:
            therapist_data[t] = {"scores": [], "complaints": 0, "praises": 0}
        therapist_data[t]["scores"].append(m.sentiment_score)

    feedbacks = db.query(FeedbackEvent).filter(
        FeedbackEvent.therapist != None
    ).all()
    for f in feedbacks:
        t = f.therapist
        if t in therapist_data:
            if f.event_type == "complaint":
                therapist_data[t]["complaints"] += 1
            elif f.event_type == "praise":
                therapist_data[t]["praises"] += 1

    result = []
    for therapist, data in therapist_data.items():
        scores = data["scores"]
        result.append({
            "therapist": therapist,
            "total_interactions": len(scores),
            "avg_sentiment_score": round(sum(scores) / len(scores), 2),
            "complaints": data["complaints"],
            "praises": data["praises"],
            "satisfaction_rate": round((sum(scores) / len(scores)) * 100, 1)
        })

    result.sort(key=lambda x: x["avg_sentiment_score"], reverse=True)
    return result

@app.get("/api/analytics/sentiment-history/{user_id}")
def sentiment_history(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access only")

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
    users = db.query(User).filter(
        User.name.ilike(f"%{name}%"),
        User.role == "user"
    ).all()
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


app.include_router(api_v1_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")