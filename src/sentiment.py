import json
import re
from llm_utils import build_llm

EVENTS = {"complaint", "praise", "concern", "neutral"}
LABELS = {"distressed", "anxious", "neutral", "hopeful", "positive"}
TARGETS = {"therapist", "service", "child_progress", "self_situation", "none", "unclear"}
INTENSITIES = {"calm", "frustrated", "highly_emotional"}

DEFAULT = {
    "score": 0.5, "label": "neutral", "event_type": "neutral", "summary": None,
    "complaint_target": None, "emotional_intensity": None, "is_specific": None, "triage_reason": None,
}


def _normalise(raw: dict) -> dict:
    out = dict(DEFAULT)
    try:
        out["score"] = min(1.0, max(0.0, float(raw.get("score", 0.5))))
    except (TypeError, ValueError):
        pass
    if raw.get("label") in LABELS:
        out["label"] = raw["label"]
    if raw.get("event_type") in EVENTS:
        out["event_type"] = raw["event_type"]
    if out["event_type"] in ("complaint", "praise") and raw.get("summary"):
        out["summary"] = str(raw["summary"])[:300]
    if raw.get("complaint_target") in TARGETS:
        out["complaint_target"] = raw["complaint_target"]
    if raw.get("emotional_intensity") in INTENSITIES:
        out["emotional_intensity"] = raw["emotional_intensity"]
    if isinstance(raw.get("specific"), bool):
        out["is_specific"] = raw["specific"]
    if raw.get("reason"):
        out["triage_reason"] = str(raw["reason"])[:300]
    return out


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def analyse_sentiment(message: str, api_key: str, baseline: float = None) -> dict:
    """Mood of one parent message, plus (for complaints) who it is about and how emotional the parent is.
    baseline = the parent's recent average mood (0-1), if known."""
    base_line = (f"\nThis parent's recent average mood is {baseline:.2f} (0 = very distressed, 1 = very positive)."
                 if baseline is not None else "")
    prompt = f"""Analyse this message from a parent using a mental health support chatbot for a child psychology centre.{base_line}

Message: "{message}"

Respond ONLY with a JSON object, no explanation, no markdown:
{{
  "score": <float 0.0 to 1.0, where 0.0 is very distressed and 1.0 is very positive>,
  "label": <one of: "distressed", "anxious", "neutral", "hopeful", "positive">,
  "event_type": <one of: "complaint", "praise", "concern", "neutral">,
  "summary": <one sentence ONLY if event_type is complaint or praise, otherwise null>,
  "complaint_target": <who or what a complaint is about, one of: "therapist" (the therapist's own conduct, skills, communication, attitude, punctuality or methods), "service" (waiting time, fees, booking, facilities), "child_progress" (the child is not improving, no person blamed), "self_situation" (the parent's own stress, exhaustion or family situation), "unclear", "none" (not a complaint)>,
  "emotional_intensity": <one of: "calm", "frustrated", "highly_emotional" (crying, hopeless, extreme or all-or-nothing language, blaming everyone, unable to think clearly)>,
  "specific": <true if it describes a concrete event or behaviour (e.g. "she cancelled twice this month"), false if vague or general (e.g. "nothing works", "they don't care")>,
  "reason": <a short phrase explaining the target and intensity you chose>
}}"""
    try:
        content = build_llm(api_key, temperature=0.1).invoke(prompt).content
        if isinstance(content, list):
            content = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        return _normalise(_extract_json(content))
    except Exception as e:
        print(f"Sentiment analysis failed: {e}")
        return dict(DEFAULT)
