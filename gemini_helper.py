import os
import re
import json
import time
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# gemini-2.0-flash-lite: free tier, stable, supports response_mime_type properly
MODEL = "gemini-2.0-flash-lite"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent?key={GEMINI_API_KEY}"
)

MAX_RETRIES = 4
INITIAL_WAIT = 15


def _call_gemini(body: dict) -> str:
    """Call Gemini with exponential backoff on 429 errors."""
    wait = INITIAL_WAIT
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.post(GEMINI_URL, json=body, timeout=60)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", wait))
            actual_wait = max(retry_after, wait)
            print(f"[Gemini] 429 hit. Attempt {attempt}/{MAX_RETRIES}. Waiting {actual_wait}s...")
            time.sleep(actual_wait)
            wait *= 2
            continue

        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        print(f"[Gemini] Raw response (first 200 chars): {raw[:200]}")
        return raw

    raise RuntimeError(f"Gemini API still returning 429 after {MAX_RETRIES} retries.")


def _extract_json(raw: str) -> dict:
    """
    Extract JSON wrapped in <json>...</json> tags.
    This is the most reliable extraction method — model is told to
    wrap output in tags, so we just slice between them.
    Falls back to regex brace-matching if tags are missing.
    """
    # Primary: extract between <json> tags
    tag_match = re.search(r'<json>(.*?)</json>', raw, re.DOTALL)
    if tag_match:
        candidate = tag_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            print(f"[Gemini] Tag extraction found content but JSON invalid: {e}")
            print(f"Content was: {candidate[:300]}")

    # Fallback: strip markdown and find outermost { }
    cleaned = raw
    for ch in ["```json", "```", "***", "**", "*"]:
        cleaned = cleaned.replace(ch, "")

    brace_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if brace_match:
        candidate = brace_match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            print(f"[Gemini] Brace fallback found content but JSON invalid: {e}")

    print(f"[Gemini] FULL raw response:\n{raw}")
    raise ValueError(f"Could not extract valid JSON. First 300 chars: {raw[:300]}")


def generate_workout(split, working_weights, history):
    """Ask Gemini to generate a structured workout plan for today."""

    history_summary = _summarise_history(history, split)

    prompt = f"""You are an expert personal trainer for an ADVANCED gym-goer (3+ years, machines + free weights).

TODAY'S SPLIT: {split}

WORKING WEIGHTS (use these exactly, do not change):
{json.dumps(working_weights, indent=2)}

RECENT HISTORY FOR THIS SPLIT (vary exercises and muscle zones from these):
{history_summary}

MUSCLE TARGETING GUIDE:
PUSH: Chest zones: Upper=Incline Press/Fly, Middle=Flat Bench/Pec Dec, Lower=Decline/High-to-Low Cable. Triceps: Long Head=Overhead Extension/Skull Crushers (needs overhead position), Lateral=Bar Pushdown/CG Bench, Medial=Reverse Pushdown. Vary zones between Push Day 1 and Push Day 2.
PULL: Back: Width=Lat Pulldown/Pullup, Thickness=Barbell Row/Cable Row, Rear=Face Pulls/Reverse Pec Dec. Biceps: Long Head (peak)=Incline Curl/Hammer, Short Head (width)=Preacher/Concentration. Alternate width vs thickness across Pull days.
LEGS: Hit all — Quads=Squat/Leg Press, Hamstrings=RDL/Leg Curl, Glutes=Hip Thrust/Bulgarian Split Squat, Calves=Calf Raise.
SHOULDERS: Prioritise Side Delts and Rear Delts. Front delts already hit on Push days.

RULES:
1. Exactly 7 exercises.
2. Use working_kg values exactly.
3. Vary from history — different angles, different exercises.
4. Exactly 1-2 supersets and 1 dropset.
5. Rep ranges: compounds 4-8 reps, isolations 10-15 reps.
6. Compound barbell lifts (Bench Press, Deadlift, Squat, OHP, Barbell Row) = alternative must be null.
7. Machine/isolation exercises = provide 1 alternative targeting same muscle head.
8. Cardio finisher: LISS 15-20 min. Leg day only: 10 min.

IMPORTANT: Wrap your entire JSON response inside <json> and </json> tags like this:
<json>
{{"exercises":[...],"cardio":{{...}}}}
</json>

The JSON must follow this exact structure:
{{
  "exercises": [
    {{
      "name": "Exercise Name",
      "muscle": "Zone — Head (Anatomical Name), e.g. Upper Chest — Clavicular Head (Pectoralis Major)",
      "sets": 4,
      "reps": "6-8",
      "weight_kg": 60.0,
      "type": "normal",
      "partner": null,
      "alternative": null,
      "note": "coaching tip or null"
    }}
  ],
  "cardio": {{
    "exercise": "Incline Treadmill Walk",
    "duration": "20 min",
    "hr_target": "125-135 BPM",
    "note": "Keep pace conversational"
  }}
}}

type must be one of: normal, superset, dropset
partner: name of superset partner exercise, or null
alternative: "Alt: Exercise Name (muscle head)" for machines/isolations, null for compounds

Generate the {split} workout now:"""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        },
    }

    raw = _call_gemini(body)
    return _extract_json(raw)


def generate_weekly_summary(history):
    """Ask Gemini to generate a Sunday weekly summary."""

    last_7 = history[-7:] if len(history) >= 7 else history
    slim = [
        {
            "date": h.get("date"),
            "split": h.get("split"),
            "exercises": h.get("exercise_names", ""),
            "volume": h.get("total_volume_kg", 0),
        }
        for h in last_7
    ]

    prompt = f"""You are a personal trainer. Write a weekly workout summary for Telegram.

Last 7 days of logs:
{json.dumps(slim, indent=2)}

Cover:
1. Sessions completed and splits done
2. Volume highlights per muscle group
3. 2-3 specific recommendations for next week
4. A short motivational closing line

Under 250 words. Use *bold* for headings. Plain text only."""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 600},
    }

    raw = _call_gemini(body)
    return f"📊 *Weekly Summary*\n━━━━━━━━━━━━━━━━━━━━━━\n{raw.strip()}"


def _summarise_history(history, split):
    """Return last 2 sessions of the same split."""
    same = [h for h in history if h.get("split") == split][-2:]
    if not same:
        return "No previous sessions for this split yet."
    return "\n".join(
        f"Date: {s.get('date')} | Exercises: {s.get('exercise_names', 'N/A')}"
        for s in same
    )
