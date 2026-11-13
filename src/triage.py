"""Decides whether a parent's complaint looks like a real concern about the therapist or emotional venting.
Pure rules on top of the LLM's labels, so it is easy to test and explain."""

THERAPIST_CONCERN = "therapist_concern"
EMOTIONAL_VENTING = "emotional_venting"
UNCLEAR = "unclear"
NOT_ABOUT_THERAPIST = "not_about_therapist"


def classify(event_type, target, intensity, specific, score, baseline=None):
    """Returns (triage_class, reason). Only complaints are triaged; anything else returns (None, None)."""
    if event_type != "complaint":
        return None, None
    dropped = baseline is not None and score is not None and (baseline - score) >= 0.3 and score < 0.4
    emotional = intensity == "highly_emotional" or (score is not None and score < 0.2) or dropped

    if target == "therapist":
        if specific and not emotional:
            return THERAPIST_CONCERN, "Specific complaint about the therapist, and the parent was not highly emotional."
        if specific and emotional:
            return UNCLEAR, "Specific complaint about the therapist, but the parent was highly emotional. Verify with a follow-up."
        if emotional:
            return EMOTIONAL_VENTING, "Vague complaint while the parent was highly emotional."
        return UNCLEAR, "Complaint about the therapist without concrete details."
    if target in ("service", "child_progress", "self_situation"):
        if emotional:
            return EMOTIONAL_VENTING, "Parent seems overwhelmed, and the complaint is not about the therapist."
        return NOT_ABOUT_THERAPIST, "Complaint is about the centre, the child's progress or the parent's situation, not the therapist."
    if emotional:
        return EMOTIONAL_VENTING, "Highly emotional message with no clear target."
    return UNCLEAR, "Complaint with no clear target."
