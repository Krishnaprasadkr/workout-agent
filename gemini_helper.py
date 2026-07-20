import os
import re
import json
import time
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Model fallback chain — updated July 2026
# gemini-2.0-flash and gemini-1.5-flash shut down June 1, 2026
# Current free tier models: gemini-3.1-flash-lite, gemini-2.5-flash-lite, gemini-3-flash-preview
MODELS = [
    "gemini-3.1-flash-lite",      # Free, fast, high quality — primary
    "gemini-2.5-flash-lite",      # Free, reliable fallback
    "gemini-3-flash-preview",     # Free preview, secondary fallback
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
    Extract JSON from Gemini response.
    Handles <json> tags, *** replacing braces/brackets, and markdown fences.
    """
    # Step 1: grab content inside <json>...</json> tags if present
    tag_match = re.search(r'<json>(.*?)</json>', raw, re.DOTALL)
    content = tag_match.group(1).strip() if tag_match else raw

    # Step 2: strip markdown fences
    for ch in ["```json", "```"]:
        content = content.replace(ch, "")
    content = content.strip()

    # Step 3: if *** is being used instead of { } — fix it
    # Gemini sometimes replaces { and } (and even [ ]) with ***
    # We detect this when *** is present but { is absent
    if "***" in content and "{" not in content:
        content = _rebuild_from_stars(content)

    # Step 4: find outermost { } block and parse
    brace_match = re.search(r'\{.*\}', content, re.DOTALL)
    if brace_match:
        candidate = brace_match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            print(f"[Gemini] JSON parse failed: {e}")
            print(f"[Gemini] Attempted:\n{candidate[:400]}")

    print(f"[Gemini] FULL raw response:\n{raw}")
    raise ValueError(f"Could not extract JSON. First 300 chars: {raw[:300]}")


def _rebuild_from_stars(content: str) -> str:
    """
    Reconstruct valid JSON braces when Gemini uses *** instead of { and }.
    Strategy: walk line by line, replace *** with { or } based on what follows.
    - *** followed by a "key": line → opening {
    - *** followed by a closing ] or another *** or end → closing }
    - lone [ and ] are usually intact; only {} get replaced with ***
    """
    lines = content.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "***":
            # Peek ahead to decide open vs close
            next_content = ""
            for j in range(i + 1, min(i + 4, len(lines))):
                ns = lines[j].strip()
                if ns:
                    next_content = ns
                    break
            # Opening brace if next meaningful line has a JSON key pattern
            if re.match(r'^"[^"]+"\s*:', next_content) or next_content.startswith('"exercises"') or next_content.startswith('"cardio"'):
                out.append(line.replace("***", "{"))
            else:
                out.append(line.replace("***", "}"))
        else:
            out.append(line)
        i += 1
    return "\n".join(out)


def generate_workout(split, working_weights, history, today=None):
    """Ask Gemini to generate a structured workout plan for today."""

    history_summary = _summarise_history(history, split)

    # Determine if today is Friday Pull (day index 4 = Friday in Mon=0 system)
    # Friday Pull comes right before Saturday Legs — Deadlift banned to protect recovery
    is_friday_pull = False
    if today is not None and split == "Pull":
        day_idx = today.weekday()  # Mon=0, Fri=4
        is_friday_pull = (day_idx == 4)

    # Build split-specific structure instructions
    if split == "Push":
        split_structure = """PUSH DAY — CHEST + TRICEPS ONLY. No shoulder, lateral raise, rear delt, or OHP.

MANDATORY EXERCISE ORDER (strictly follow positions 1-7):
  Position 1: Heavy chest compound — Flat Barbell Bench Press (ALWAYS first, ALWAYS)
  Position 2: Secondary chest compound — Incline DB Press or Incline Barbell Press
  Position 3: Chest isolation — Pec Dec / Cable Fly / High-to-Low Cable Fly
  Position 4: Tricep compound — Close Grip Bench or Weighted Dips
  Position 5: Tricep long head isolation — Overhead Tricep Extension or Skull Crushers (arm must go overhead)
  Position 6: Tricep lateral head isolation — Straight Bar Pushdown or Rope Pushdown
  Position 7: Second chest or tricep isolation (vary from history)

CHEST ZONES: Upper=Incline movements, Middle=Flat/Pec Dec, Lower=Decline/High-to-Low Cable
TRICEP HEADS: Long Head=overhead movements, Lateral=pushdowns, Medial=reverse grip pushdown
Vary chest zone emphasis between Push Day 1 and Push Day 2."""

    elif split == "Pull":
        if is_friday_pull:
            split_structure = """PULL DAY (FRIDAY) — BACK + BICEPS ONLY. No shoulder exercises.

⚠️ FRIDAY RULE: Deadlift is BANNED today. Saturday is Legs — Deadlift would destroy recovery.

MANDATORY EXERCISE ORDER (strictly follow positions 1-7):
  Position 1: Heavy back compound ROW (choose ONE from: Barbell Bent Over Row, Chest-Supported DB Row, Meadows Row, Pendlay Row, T-Bar Row) — NO DEADLIFT
  Position 2: Back width compound — Lat Pulldown or Wide Grip Pullup
  Position 3: Secondary back row — Seated Cable Row or Single Arm DB Row
  Position 4: Back isolation — Straight Arm Pulldown or Cable Pullover
  Position 5: Rear delt — Face Pulls or Reverse Pec Dec
  Position 6: Bicep compound — Barbell Curl or Incline DB Curl
  Position 7: Bicep isolation — Hammer Curl or Concentration Curl or Preacher Curl

BACK FOCUS: Width=Lat Pulldown/Pullup, Thickness=Row movements
BICEP HEADS: Long Head (peak)=Incline/Hammer Curl, Short Head (width)=Preacher/Concentration Curl"""
        else:
            split_structure = """PULL DAY (TUESDAY) — BACK + BICEPS ONLY. No shoulder exercises.

MANDATORY EXERCISE ORDER (strictly follow positions 1-7):
  Position 1: Deadlift — COMPULSORY, always position 1 on Tuesday Pull (heaviest compound, done first)
  Position 2: Back width compound — Lat Pulldown or Wide Grip Pullup
  Position 3: Back thickness compound — Seated Cable Row or Barbell Row
  Position 4: Back isolation — Straight Arm Pulldown or Cable Pullover
  Position 5: Rear delt — Face Pulls or Reverse Pec Dec
  Position 6: Bicep compound — Barbell Curl or Incline DB Curl
  Position 7: Bicep isolation — Hammer Curl or Concentration Curl or Preacher Curl

BACK FOCUS: Width=Lat Pulldown/Pullup, Thickness=Seated Row/Barbell Row
BICEP HEADS: Long Head (peak)=Incline/Hammer Curl, Short Head (width)=Preacher/Concentration Curl"""

    elif split == "Legs":
        split_structure = """LEGS DAY — LOWER BODY ONLY. No upper body exercises.

MANDATORY EXERCISE ORDER (strictly follow positions 1-7):
  Position 1: Heavy quad compound — Barbell Squat (ALWAYS first)
  Position 2: Secondary quad compound — Leg Press or Hack Squat
  Position 3: Hamstring compound — Romanian Deadlift (DB or Barbell)
  Position 4: Hamstring isolation — Leg Curl (machine)
  Position 5: Glute isolation — Hip Thrust or Bulgarian Split Squat
  Position 6: Quad isolation — Leg Extension (machine)
  Position 7: Calves — Standing Calf Raise or Seated Calf Raise

Hit all four muscle groups: Quads, Hamstrings, Glutes, Calves — every session."""

    elif split == "Shoulders":
        split_structure = """SHOULDERS DAY — SIDE DELTS ARE THE PRIORITY. Front delts already trained heavily on both Push days.

MANDATORY EXERCISE ORDER (strictly follow positions 1-7):
  Position 1: Dumbbell Lateral Raise — ALWAYS this exact exercise, ALWAYS first. 4 sets. Side delts are the priority.
  Position 2: Overhead Press (DB or Barbell) — 3 sets only, MODERATE weight. Front delt maintenance, NOT the focus.
  Position 3: Rear delt compound — Face Pulls or Bent Over Lateral Raise
  Position 4: Rear delt isolation — Reverse Pec Dec
  Position 5: Trap compound — Smith Machine Shrugs or Barbell Shrugs
  Position 6: Wrist Curls (barbell or dumbbell) — Forearms — Flexor Carpi Radialis. ALWAYS position 6.
  Position 7: Second rear delt or trap variation (e.g. Upright Row, Cable Rear Delt Fly, or Face Pull variant)

⚠️ STRICT SHOULDER RULES:
- Dumbbell Lateral Raise is FIXED at position 1 — do not replace it with any other lateral raise variation
- Do NOT include cable lateral raise or machine lateral raise — Dumbbell Lateral Raise covers side delts for this session
- OHP goes at position 2 only, 3 sets, lighter weight than compound days
- Wrist Curls are FIXED at position 6 — always include them"""

    else:
        split_structure = f"{split.upper()} DAY — Follow compound before isolation ordering."

    prompt = f"""You are an expert personal trainer for an ADVANCED gym-goer (3+ years, machines + free weights).

TODAY'S SPLIT: {split}{'  [FRIDAY PULL — NO DEADLIFT]' if is_friday_pull else ''}

WORKING WEIGHTS (use these exactly, do not change):
{json.dumps(working_weights, indent=2)}

RECENT HISTORY FOR THIS SPLIT (vary exercises from these, do not repeat same session):
{history_summary}

{split_structure}

UNIVERSAL RULES (apply to ALL splits):
1. Exactly 7 exercises — no more, no less.
2. Use working_kg values EXACTLY as provided — do not change any weight.
3. STRICT ORDER: Compounds always before isolations. Never place an isolation exercise before all compounds are done.
4. NO DUPLICATES: Do not include two exercises that target the same muscle head with the same movement pattern in one session. e.g. Do not include both Dumbbell Lateral Raise AND Cable Lateral Raise in the same workout.
5. Supersets and dropsets on isolation exercises only — never on position 1 compound.
6. Exactly 1-2 supersets and 1 dropset per session total.
7. Rep ranges: heavy compounds (position 1-2) = 4-6 reps, secondary compounds = 6-8 reps, isolations = 10-15 reps.
8. Compound barbell lifts (Bench Press, Deadlift, Squat, OHP, Barbell Row): alternative = null.
9. Machine/isolation exercises: provide 1 alternative targeting same muscle head.
10. Cardio finisher: LISS 15-20 min after session. Leg day only: 10 min (legs are taxing enough).

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
