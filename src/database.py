import os
from sqlalchemy import create_engine, Column, Integer, String, Text, Date, ForeignKey, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # 每次从连接池取连接前先探测一下，连接失效就自动换新的
    pool_recycle=280,     # 连接存活超过280秒就主动回收重建，避开Render的空闲超时
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password = Column(String(200), nullable=False)
    role = Column(String(10), default="user")
    created_at = Column(DateTime, default=datetime.utcnow)

    children = relationship("Patient", back_populates="parent")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    age = Column(Integer)
    gender = Column(String(10))
    diagnosis = Column(String(200))
    parent_id = Column(Integer, ForeignKey("users.id"))

    parent = relationship("User", back_populates="children")
    records = relationship("MedicalRecord", back_populates="patient")


class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    date = Column(Date, nullable=False)
    diagnosis = Column(String(200))
    treatment = Column(Text)
    notes = Column(Text)
    therapist = Column(String(100))

    patient = relationship("Patient", back_populates="records")

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    therapist = Column(String(100), nullable=False)
    date = Column(Date, nullable=False)
    time = Column(String(20), nullable=False)
    type = Column(String(100))
    status = Column(String(20), default="scheduled")
    notes = Column(Text)

    patient = relationship("Patient")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
    messages = relationship("ChatMessage", back_populates="session", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    sentiment_score = Column(Float, nullable=True)
    sentiment_label = Column(String(20), nullable=True)
    related_therapist = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
    therapist = Column(String(100), nullable=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True)
    sentiment_score = Column(Float, nullable=True)
    event_type = Column(String(20), nullable=True)
    content_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()