import os, time
from collections import defaultdict

# Shown in the crisis card. Verify numbers are current before the demo; add more here.
HOTLINES = [{"name": "Helpline HEAL", "number": "15555"}]

_KEYWORDS = [
    "suicide", "kill myself", "end my life", "want to die", "don't want to live",
    "dont want to live", "self-harm", "self harm", "hurt myself", "better off dead",
    "bunuh diri", "nak mati", "tak nak hidup", "mencederakan diri", "tamatkan hidup",
    "自杀", "想死", "不想活", "轻生", "自残", "伤害自己", "结束生命", "活不下去",
]

CRISIS_FALLBACK = (
    "I'm really sorry you are going through this, and I'm glad you told me. "
    "You don't have to face it alone. Please reach out right now to Helpline HEAL at 15555, "
    "or call your local emergency number if you are in immediate danger. "
    "If someone is with you, please let them know how you feel."
)


def detect_crisis(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _KEYWORDS)


_hits = defaultdict(list)


def rate_ok(key: str, limit: int = 8, window: int = 60) -> bool:
    """Simple in-memory per-IP limit for the public guest endpoint."""
    now = time.time()
    _hits[key] = [t for t in _hits[key] if now - t < window]
    if len(_hits[key]) >= limit:
        return False
    _hits[key].append(now)
    return True


IP_DAILY = int(os.getenv("GUEST_IP_DAILY", "30"))         # messages per visitor IP per day
GLOBAL_DAILY = int(os.getenv("GUEST_GLOBAL_DAILY", "400"))  # all visitors together per day
_day = {"d": None, "g": 0}
_ip_day = defaultdict(int)


def check_guest(ip: str):
    """Returns (allowed, message, remaining_for_this_visitor). In-memory: resets on restart."""
    today = time.strftime("%Y-%m-%d")
    if _day["d"] != today:
        _day.update(d=today, g=0)
        _ip_day.clear()
    if not rate_ok(ip):
        return False, "You are sending messages very quickly. Please wait a minute and try again.", None
    if _day["g"] >= GLOBAL_DAILY:
        return False, "The visitor chat has reached its limit for today. Please try again tomorrow, or call us on +60 3-1234 5678.", 0
    if _ip_day[ip] >= IP_DAILY:
        return False, "You have reached today's visitor limit. Please try again tomorrow, log in, or call us on +60 3-1234 5678.", 0
    _day["g"] += 1
    _ip_day[ip] += 1
    return True, "", IP_DAILY - _ip_day[ip]
