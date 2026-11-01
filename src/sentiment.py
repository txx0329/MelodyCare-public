import os
import json
from llm_utils import build_llm


def analyse_sentiment(message: str, api_key: str) -> dict:
    """
    Returns:
        {
            "score": 0.0-1.0,  (0=very negative, 1=very positive)
            "label": "distressed" | "anxious" | "neutral" | "hopeful" | "positive",
            "event_type": "complaint" | "praise" | "neutral" | "concern",
            "summary": "one sentence summary if complaint/praise, else None"
        }
    """
    llm = build_llm(api_key, temperature=0.1)

    prompt = f"""Analyse the sentiment of this message from a parent using a mental health support chatbot.

Message: "{message}"

Respond ONLY with a JSON object, no explanation, no markdown:
{{
  "score": <float 0.0 to 1.0, where 0.0 is very distressed and 1.0 is very positive>,
  "label": <one of: "distressed", "anxious", "neutral", "hopeful", "positive">,
  "event_type": <one of: "complaint", "praise", "concern", "neutral">,
  "summary": <one sentence summary ONLY if event_type is complaint or praise, otherwise null>
}}"""

    try:
        response = llm.invoke(prompt)
        content = response.content
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content.strip())
    except Exception as e:
        print(f"Sentiment analysis failed: {e}")
        return {
            "score": 0.5,
            "label": "neutral",
            "event_type": "neutral",
            "summary": None
        }