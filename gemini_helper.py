import os
import re
import json
import time
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Model fallback chain — if one hits 429 or fails, tries the next
MODELS = [
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-2.5-flash-lite",
]

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

MAX_RETRIES = 3
INITIAL_WAIT = 20


def _call_gemini(body: dict) -> str:
    """
    Try each model in the fallback chain.
    Within each model, retry up to MAX_RETRIES times on 429 with backoff.
    """
    last_error = None

    for model in MODELS:
        url = BASE_URL.format(model=model, key=GEMINI_API_KEY)
        print(f"[Gemini] Trying model: {model}")
        wait = INITIAL_WAIT

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(url, json=body, timeout=60)

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", wait))
                    actual_wait = max(retry_after, wait)
                    print(f"[Gemini] 429 on {model}. Attempt {attempt}/{MAX_RETRIES}. Waiting {actual_wait}s...")
                    time.sleep(actual_wait)
                    wait *= 2
                    continue

                if resp.status_code == 404:
                    print(f"[Gemini] 404 — model {model} not found. Trying next model.")
                    break  # skip to next model immediately

                resp.raise_for_status()
                raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                print(f"[Gemini] Success with model: {model}")
                print(f"[Gemini] Raw response (first 200 chars): {raw[:200]}")
                return raw

            except requests.exceptions.RequestException as e:
                print(f"[Gemini] Request error on {model}: {e}")
                last_error = e
                break  # try next model

        else:
            # All retries exhausted for this model
            print(f"[Gemini] All retries exhausted for {model}. Trying next model...")
            last_error = RuntimeError(f"429 persisted on {model} after {MAX_RETRIES} retries")

    raise RuntimeError(
        f"All models failed. Last error: {last_error}\n"
        "Quota may be exhausted for today. The agent will work normally tomorrow."
    )


def _extract_json(raw: str) -> dict:
    """
    Extract JSON from response.
    Primary: looks for <json>...</json> tags.
    Fallback: strips markdown and finds outermost { } block.
    """
    # Primary: tag-based extraction
    tag_match = re.search(r'<json>(.*?)</json>', raw, re.DOTALL)
    if tag_match:
        candidate = tag_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            print(f"[Gemini] Tag content found but invalid JSON: {e}")

    # Fallback: strip markdown characters and find outermost { }
    cleaned = raw
    for ch in ["```json", "```", "***", "**", "*"]:
        cleaned = cleaned.replace(ch, "")

    brace_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if brace_match:
        candidate = brace_match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            print(f"[Gemini] Brace fallback invalid JSON: {e}")

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
PUSH (CHEST + TRICEPS ONLY — NO shoulder exercises):
  Chest zones: Upper=Incline Press/Fly, Middle=Flat Bench/Pec Dec, Lower=Decline/High-to-Low Cable Fly.
  Triceps heads: Long Head=Overhead Extension/Skull Crushers (arm overhead), Lateral=Bar Pushdown/Close Grip Bench, Medial=Reverse Grip Pushdown.
  ⚠️ STRICT RULE: For PUSH sessions, use ONLY chest and tricep exercises. Do NOT include any shoulder, lateral raise, rear delt, or overhead press exercises. Shoulders have their own dedicated day.
  Vary chest zone emphasis and tricep head focus between Push Day 1 and Push Day 2.

PULL (BACK + BICEPS ONLY — NO shoulder exercises):
  Back: Width=Lat Pulldown/Pullup, Thickness=Barbell Row/Cable Row, Rear Delt=Face Pulls/Reverse Pec Dec.
  Biceps: Long Head (peak)=Incline Curl/Hammer Curl, Short Head (width)=Preacher/Concentration Curl.
  Alternate width vs thickness focus across Pull Day 1 and Pull Day 2.

LEGS (LOWER BODY ONLY):
  Quads=Squat/Leg Press, Hamstrings=RDL/Leg Curl, Glutes=Hip Thrust/Bulgarian Split Squat, Calves=Standing/Seated Calf Raise.
  Hit all four muscle groups every leg session.

SHOULDERS (DEDICATED DAY — deltoids and traps only):
  Side Delts (priority)=Lateral Raises/Cable Lateral, Rear Delts (priority)=Reverse Pec Dec/Face Pulls/Bent Over Lateral, Front Delts (minimal — already trained on Push)=Light OHP, Traps=Shrugs/Upright Row.

RULES:
1. Exactly 7 exercises.
2. Use working_kg values exactly as provided.
3. Vary exercises from history — different angles, different exercises.
4. Exactly 1-2 supersets and 1 dropset per session.
5. Rep ranges: compounds 4-8 reps, isolations 10-15 reps.
6. Compound barbell lifts (Bench Press, Deadlift, Squat, OHP, Barbell Row): alternative must be null.
7. Machine/isolation exercises: provide 1 alternative targeting same muscle head.
8. Cardio finisher: LISS 15-20 min. Leg day only: 10 min.

Wrap your entire response inside <json> and </json> tags. Output valid JSON only inside those tags.

<json>
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
</json>

type = normal | superset | dropset
partner = superset partner exercise name, or null
alternative = "Alt: Exercise Name (muscle head)" for machines/isolations, null for compound barbell lifts

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
