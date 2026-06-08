import os
import json
import time
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# gemini-1.5-flash-8b has the most generous free limits:
# 15 RPM, 1000 RPD, 1M tokens/day — perfect for one daily call
MODEL = "gemini-1.5-flash-8b"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent?key={GEMINI_API_KEY}"
)

MAX_RETRIES = 4
INITIAL_WAIT = 15  # seconds before first retry after 429


def _call_gemini(body: dict) -> str:
    """Call Gemini with exponential backoff on 429 errors."""
    wait = INITIAL_WAIT
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.post(GEMINI_URL, json=body, timeout=60)

        if resp.status_code == 429:
            # Check if Gemini tells us how long to wait
            retry_after = int(resp.headers.get("Retry-After", wait))
            actual_wait = max(retry_after, wait)
            print(f"[Gemini] 429 Rate limit hit. Attempt {attempt}/{MAX_RETRIES}. "
                  f"Waiting {actual_wait}s before retry...")
            time.sleep(actual_wait)
            wait *= 2  # exponential backoff: 15 → 30 → 60 → 120
            continue

        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return raw

    raise RuntimeError(
        f"Gemini API still returning 429 after {MAX_RETRIES} retries. "
        "Try running the agent again in a few minutes."
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

    raw = _call_gemini(body)
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(clean)


def generate_weekly_summary(history):
    """Ask Gemini to generate a Sunday weekly summary."""

    last_7 = history[-7:] if len(history) >= 7 else history
    # Only send exercise_names + split + date to keep tokens low
    slim = [
        {"date": h.get("date"), "split": h.get("split"),
         "exercises": h.get("exercise_names", ""), "volume": h.get("total_volume_kg", 0)}
        for h in last_7
    ]

    prompt = f"""
You are a personal trainer. Here are the last 7 days of workout logs:

{json.dumps(slim, indent=2)}

Write a concise weekly summary for Telegram covering:
1. Sessions completed and splits done
2. Volume highlights per muscle group
3. 2-3 specific recommendations for next week
4. A short motivational closing line

Keep it under 250 words. Format for Telegram (use *bold* for headings).
"""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 500},
    }

    raw = _call_gemini(body)
    return f"📊 *Weekly Summary*\n━━━━━━━━━━━━━━━━━━━━━━\n{raw.strip()}"


def _summarise_history(history, split):
    """Return last 2 sessions of the same split — minimal tokens."""
    same = [h for h in history if h.get("split") == split][-2:]
    if not same:
        return "No previous sessions for this split yet."
    lines = []
    for s in same:
        lines.append(f"Date: {s.get('date')} | Exercises: {s.get('exercise_names', 'N/A')}")
    return "\n".join(lines)
