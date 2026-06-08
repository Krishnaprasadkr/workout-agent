import os
import re
import json
import time
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# gemini-3-flash-preview: free tier, 10 RPM, 1500 RPD — perfect for one daily call
MODEL = "gemini-3-flash-preview"
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
        print(f"[Gemini] Raw response (first 300 chars): {raw[:300]}")
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

RECENT HISTORY FOR THIS SPLIT (use this to vary focus and avoid repeating the same angles):
{history_summary}

MUSCLE HEAD TARGETING GUIDE — use this to ensure complete development:

PUSH (Chest + Triceps):
  Chest zones:
    - Upper chest: Incline Barbell/DB Press, Incline Cable Fly, Low-to-High Cable Fly
    - Middle chest: Flat Bench Press, Pec Dec Fly, Cable Crossover at chest height
    - Lower chest: Decline Press, Dips (forward lean), High-to-Low Cable Fly
  Tricep heads:
    - Long head (biggest): Overhead Tricep Extension, Skull Crushers — arm must go OVERHEAD to fully stretch long head
    - Lateral head: Straight Bar Pushdown, Close Grip Bench Press
    - Medial head: Reverse Grip Pushdown, Dips (upright torso)
  Strategy: Intelligently vary chest zone emphasis and tricep head focus between Push Day 1 and Push Day 2 based on history. Cover different angles each session so all zones get trained across the week.

PULL (Back + Biceps):
  Back focus:
    - Width (V-taper): Lat Pulldown, Wide Grip Pull-Up, Straight Arm Pushdown
    - Thickness (mass): Barbell/DB Row, Seated Cable Row, T-Bar Row
    - Rear delts: Face Pulls, Reverse Pec Dec, Bent Over Lateral Raise
  Bicep heads:
    - Long head (peak): Incline DB Curl, Hammer Curl (also hits brachialis)
    - Short head (width): Preacher Curl, Concentration Curl, Close Grip Barbell Curl
  Strategy: Alternate between width-focus and thickness-focus across Pull Day 1 and Pull Day 2.

LEGS:
  - Quads: Barbell Squat, Leg Press, Hack Squat, Leg Extension
  - Hamstrings: Romanian Deadlift, Leg Curl, Stiff Leg Deadlift
  - Glutes: Hip Thrust, Bulgarian Split Squat, Sumo Squat
  - Calves: Standing Calf Raise (gastrocnemius), Seated Calf Raise (soleus)
  Strategy: Hit all four leg muscle groups every session.

SHOULDERS:
  - Front delt: Overhead Press (already worked in Push — minimal extra volume needed)
  - Side delt (KEY for width): Lateral Raises, Cable Lateral Raise, Machine Lateral Raise
  - Rear delt (KEY for posture): Reverse Pec Dec, Face Pulls, Bent Over Lateral Raise
  - Traps: Shrugs, Upright Row
  Strategy: Prioritise side delts and rear delts heavily since front delts get volume from Push days.

RULES:
1. Generate EXACTLY 7 exercises — no more, no less.
2. Use the working_kg values provided — do NOT change the weights.
3. Vary exercise selection and muscle zone focus compared to the recent history shown above.
4. Add exactly 1-2 supersets and exactly 1 dropset per session for intensity.
5. Include a cardio finisher for fat loss (LISS, 15-20 min, suitable after this split).
6. For leg day: cardio is 10 min only (legs are taxing enough).
7. Add a short coaching note for any technically demanding exercise.
8. Choose rep ranges appropriate to the exercise: compounds 4-6 or 6-8, isolations 10-15.
9. ALTERNATIVES: For compound barbell lifts (Bench Press, Deadlift, Squat, Overhead Press, Barbell Row) set alternative to null — these are compulsory. For all machine-based and isolation exercises, provide exactly 1 alternative exercise that targets the same muscle head, formatted as: "Alt: Exercise Name (same muscle target)".

RESPOND ONLY WITH THIS EXACT JSON FORMAT (no markdown, no explanation, no text before or after):
{{
  "exercises": [
    {{
      "name": "Exercise Name",
      "muscle": "Muscle Head — Anatomical Name (e.g. Upper Chest — Clavicular Head (Pectoralis Major), Triceps — Long Head (Triceps Brachii), Side Delt — Medial Deltoid)",
      "sets": 4,
      "reps": "6-8",
      "weight_kg": 60,
      "type": "normal|superset|dropset",
      "partner": "Superset partner exercise name or null",
      "alternative": "Alt: Exercise Name (same muscle target) or null for compound lifts",
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
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2000},
    }

    raw = _call_gemini(body)
    return _extract_json(raw)


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


def _extract_json(raw: str) -> dict:
    """
    Robustly extract JSON from Gemini's response.
    Handles cases where the model wraps JSON in markdown fences
    or adds conversational text before/after the JSON block.
    Strategy: find the first '{' and last '}' and extract everything between.
    """
    # Find the outermost JSON object using regex
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        print(f"[Gemini] Full raw response for debugging:\n{raw}")
        raise ValueError(
            "Gemini did not return a valid JSON object. "
            f"Raw response was: {raw[:500]}"
        )
    clean = match.group(0)
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"[Gemini] JSON parse failed. Extracted text:\n{clean[:500]}")
        raise ValueError(f"Gemini returned malformed JSON: {e}") from e


def _summarise_history(history, split):
    """Return last 2 sessions of the same split — minimal tokens."""
    same = [h for h in history if h.get("split") == split][-2:]
    if not same:
        return "No previous sessions for this split yet."
    lines = []
    for s in same:
        lines.append(f"Date: {s.get('date')} | Exercises: {s.get('exercise_names', 'N/A')}")
    return "\n".join(lines)
