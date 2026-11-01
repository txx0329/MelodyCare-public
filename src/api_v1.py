"""Public API v1: knowledge-base Q&A for partners. Never touches patient data or parent chats."""
import os, hmac, time, asyncio
from urllib.parse import urlparse
from collections import defaultdict
from typing import Literal, Optional
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from rag_chain import answer_guest
from safety import detect_crisis, rate_ok, CRISIS_FALLBACK
from llm_utils import friendly_error

router = APIRouter(prefix="/api/v1", tags=["Public API v1"])
PER_MIN = int(os.getenv("API_KEY_PER_MIN", "10"))   # requests per key per minute
DAILY = int(os.getenv("API_KEY_DAILY", "200"))      # requests per key per day
GLOBAL_DAILY = int(os.getenv("API_GLOBAL_DAILY", "600"))  # all API keys together, protects the Gemini quota
TENANT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "tenants")
_day = {"d": None}
_used = defaultdict(int)
_all = {"n": 0}


def _keys() -> dict:
    """API_KEYS env var, format  name1:key1,name2:key2"""
    out = {}
    for item in os.getenv("API_KEYS", "").split(","):
        if ":" in item:
            name, key = item.split(":", 1)
            if name.strip() and key.strip():
                out[name.strip()] = key.strip()
    return out


def _auth(x_api_key: Optional[str]) -> str:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    for name, key in _keys().items():
        if hmac.compare_digest(key.encode(), x_api_key.encode()):
            return name
    raise HTTPException(status_code=401, detail="Invalid API key.")


def _origins() -> dict:
    """API_ORIGINS env var, format  name=https://a.com|https://www.a.com;name2=https://b.com
    A key listed here is a *browser key*: it only works from those websites."""
    out = {}
    for item in os.getenv("API_ORIGINS", "").split(";"):
        if "=" in item:
            name, urls = item.split("=", 1)
            out[name.strip()] = {u.strip().rstrip("/").lower() for u in urls.split("|") if u.strip()}
    return out


def _check_origin(name: str, origin: Optional[str], host: Optional[str]):
    origin = (origin or "").rstrip("/").lower()
    if origin and host and urlparse(origin).netloc == host.lower():
        return  # our own pages (the /docs page, the demo widget)
    allowed = _origins().get(name)
    if allowed:
        if origin not in allowed:
            raise HTTPException(status_code=403, detail="This key is not allowed on this website.")
    elif origin:
        raise HTTPException(status_code=403, detail="This key is for server-side use only. Ask for a browser key for your website.")


def _tenant(name: str):
    """Optional data/tenants/<name>.txt turns a key into a partner assistant: first line 'ORG: Name', the rest is that organisation's own details."""
    path = os.path.join(TENANT_DIR, name + ".txt")
    if not os.path.isfile(path):
        return None, None  # no file = MelodyCare's own visitor assistant (clinic info included)
    org, lines = name.replace("-", " ").title(), open(path, encoding="utf-8").read().strip().splitlines()
    if lines and lines[0].upper().startswith("ORG:"):
        org, lines = lines[0][4:].strip() or org, lines[1:]
    return org, "\n".join(lines).strip()[:3000]


def _today_reset():
    today = time.strftime("%Y-%m-%d")
    if _day["d"] != today:
        _day["d"] = today
        _used.clear()
        _all["n"] = 0


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=600)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=600, description="The visitor's question (English, Bahasa Malaysia or Chinese).")
    history: list[Turn] = Field(default=[], max_length=6, description="Optional previous turns, newest last (max 6).")


class ChatOut(BaseModel):
    answer: str
    sources: list[str] = Field(description="Knowledge-base files the answer was based on.")
    crisis: bool = Field(description="True when the message suggests self-harm; show a helpline to the user.")
    remaining_today: Optional[int] = Field(description="Calls left today for this key (null for crisis replies).")


@router.post("/chat", response_model=ChatOut, summary="Ask the MelodyCare visitor assistant")
async def chat(body: ChatIn, request: Request, x_api_key: Optional[str] = Header(None, description="Your API key")):
    """Answers questions about the centre (location, parking, hours, services, team) and gives general,
    kind guidance on child wellbeing. Uses the public knowledge base only: no patient data."""
    name = _auth(x_api_key)
    _check_origin(name, request.headers.get("origin"), request.headers.get("host"))
    msg = body.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message is empty.")
    if detect_crisis(msg):  # safety first: instant, free, never blocked by limits
        return ChatOut(answer=CRISIS_FALLBACK, sources=[], crisis=True, remaining_today=None)
    _today_reset()
    if not rate_ok("api:" + name, PER_MIN, 60):
        raise HTTPException(status_code=429, detail=f"Rate limit: {PER_MIN} requests per minute per key.")
    if _all["n"] >= GLOBAL_DAILY:
        raise HTTPException(status_code=429, detail="The service has reached its daily capacity. Please try again tomorrow.")
    if _used[name] >= DAILY:
        raise HTTPException(status_code=429, detail=f"Daily limit of {DAILY} requests reached. Try again tomorrow.")
    google_key = os.getenv("GOOGLE_API_KEY")
    if not google_key:
        raise HTTPException(status_code=500, detail="Service is not configured.")
    _used[name] += 1
    _all["n"] += 1
    org, info = _tenant(name)
    history = [{"role": t.role, "content": t.content} for t in body.history]
    try:
        r = await asyncio.to_thread(answer_guest, msg, google_key, history, org, info)
    except Exception as e:
        print(f"API v1 chat error ({name}): {e}")
        raise HTTPException(status_code=503, detail=friendly_error(e))
    return ChatOut(answer=r["answer"], sources=r["sources"], crisis=False, remaining_today=DAILY - _used[name])


@router.get("/status", summary="Check your key and remaining quota")
async def status(x_api_key: Optional[str] = Header(None, description="Your API key")):
    name = _auth(x_api_key)
    _today_reset()
    return {"key_name": name, "used_today": _used[name], "daily_limit": DAILY, "per_minute_limit": PER_MIN}
