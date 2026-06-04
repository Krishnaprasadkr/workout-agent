import os
import json
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-1.5-flash:generateContent?key=" + GEMINI_API_KEY
)

def generate_workout(split, working_weights, history):
    """Ask Gemini to generate a structured workout plan for today."""

    history_summary = _summarise_history(history, split)

    prompt = f"""
You are an expert personal trainer building a daily gym workout for an ADVANCED lifter (3+ years experience).

TODAY'S SPLIT: {split}

CURRENT WORKING WEIGHTS (already calculated with progressive overload):
{json.dumps(working_weights, indent=2)}

RECENT HISTORY FOR THIS SPLIT:
{history_summary}

RULES:
1. Use the working_kg values provided — do NOT change the weights.
2. Vary exercise order and superset/dropset combinations compared to previous sessions.
3. Add 1-2 supersets and 1 dropset per session for intensity.
4. Include a cardio finisher for fat loss (LISS, 15-20 min, suitable after this split).
5. For leg day: lower cardio intensity (10 min only) since legs are taxing.
6. Add a short coaching note for any technically demanding exercise.

RESPOND ONLY WITH THIS EXACT JSON FORMAT (no markdown, no explanation):
{{
  "exercises": [
    {{
      "name": "Exercise Name",
      "muscle": "Target Muscle",
      "sets": 4,
      "reps": "8-10",
      "weight_kg": 60,
      "type": "normal|superset|dropset",
      "partner": "Superset partner exercise name or null",
      "note": "Optional coaching tip or null"
    }}
  ],
  "cardio": {{
    "exercise": "e.g. Incline Treadmill Walk",
    "duration": "20 min",
    "hr_target": "125-135 BPM",
    "note": "Short tip"
  }}
}}
"""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1500},
    }

    resp = requests.post(GEMINI_URL, json=body, timeout=30)
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    # Strip markdown fences if present
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(clean)


def generate_weekly_summary(history):
    """Ask Gemini to generate a Sunday weekly summary."""

    last_7 = history[-7:] if len(history) >= 7 else history
    summary_data = json.dumps(last_7, indent=2)

    prompt = f"""
You are a personal trainer. Here is the last 7 days of workout logs for an advanced gym goer:

{summary_data}

Write a concise, motivating weekly summary in plain text (no JSON) covering:
1. Sessions completed and splits done
2. Total estimated volume (sets × reps × weight) per muscle group
3. Exercises where progressive overload was applied
4. 2-3 specific recommendations for next week
5. A short motivational closing line

Keep it under 300 words. Use emoji sparingly. Format for Telegram (use *bold* for headings).
"""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 600},
    }

    resp = requests.post(GEMINI_URL, json=body, timeout=30)
    resp.raise_for_status()
    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return f"📊 *Weekly Summary*\n━━━━━━━━━━━━━━━━━━━━━━\n{raw.strip()}"


def _summarise_history(history, split):
    """Return last 2 sessions of the same split as a readable string."""
    same = [h for h in history if h.get("split") == split][-2:]
    if not same:
        return "No previous sessions for this split yet."
    lines = []
    for s in same:
        lines.append(f"Date: {s.get('date')} | Exercises: {s.get('exercise_names', 'N/A')}")
    return "\n".join(lines)
