import os
import re
import json
import time
import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Model fallback chain — updated July 2026
MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
]

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

MAX_RETRIES = 3
INITIAL_WAIT = 20


def _call_gemini(body: dict) -> str:
    """Try each model in fallback chain with exponential backoff on 429."""
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
                    print(f"[Gemini] 404 — model {model} not found. Trying next.")
                    break
                resp.raise_for_status()
                raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                print(f"[Gemini] Success with model: {model}")
                print(f"[Gemini] Raw response (first 200 chars): {raw[:200]}")
                return raw
            except requests.exceptions.RequestException as e:
                print(f"[Gemini] Request error on {model}: {e}")
                last_error = e
                break
        else:
            print(f"[Gemini] All retries exhausted for {model}. Trying next...")
            last_error = RuntimeError(f"429 persisted on {model}")

    raise RuntimeError(f"All models failed. Last error: {last_error}")


def _extract_json(raw: str) -> dict:
    """Extract JSON from Gemini response — handles tags, *** replacing braces, markdown."""
    tag_match = re.search(r'<json>(.*?)</json>', raw, re.DOTALL)
    content = tag_match.group(1).strip() if tag_match else raw
    for ch in ["```json", "```"]:
        content = content.replace(ch, "")
    content = content.strip()
    if "***" in content and "{" not in content:
        content = _rebuild_from_stars(content)
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
    """Reconstruct JSON braces when Gemini uses *** instead of { }."""
    lines = content.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "***":
            next_content = ""
            for j in range(i + 1, min(i + 4, len(lines))):
                ns = lines[j].strip()
                if ns:
                    next_content = ns
                    break
            if re.match(r'^"[^"]+"\s*:', next_content):
                out.append(line.replace("***", "{"))
            else:
                out.append(line.replace("***", "}"))
        else:
            out.append(line)
        i += 1
    return "\n".join(out)


def _get_last_exercise(history, split, position):
    """
    Read session history to find what exercise was used at a given position
    in the most recent session of this split.
    Returns the exercise name at that position, or None.
    """
    same_split = [h for h in history if h.get("split") == split]
    if not same_split:
        return None
    last = same_split[-1]
    try:
        plan = last.get("full_plan_json")
        if isinstance(plan, str):
            plan = json.loads(plan)
        exercises = plan.get("exercises", [])
        if position <= len(exercises):
            return exercises[position - 1].get("name")
    except Exception:
        pass
    return None


def _count_split_sessions(history, split):
    """Count how many sessions of this split exist in history."""
    return sum(1 for h in history if h.get("split") == split)


def generate_workout(split, working_weights, history, today=None):
    """Generate a structured workout plan for today."""

    history_summary = _summarise_history(history, split)
    split_count = _count_split_sessions(history, split)

    # ── Determine which alternating exercises to use ──────────────────────────
    # For OR pairs: even session count = option A, odd = option B
    # This creates automatic weekly alternation

    def alternate(option_a, option_b, count=split_count):
        return option_a if count % 2 == 0 else option_b

    def cycle3(option_a, option_b, option_c, count=split_count):
        idx = count % 3
        return [option_a, option_b, option_c][idx]

    # ── Friday Pull detection (day before Legs — no Deadlift) ─────────────────
    is_friday_pull = False
    if today is not None and split == "Pull":
        is_friday_pull = (today.weekday() == 4)  # Friday = 4

    # ── Build split-specific prompt ───────────────────────────────────────────

    if split == "Push" and today is not None and today.weekday() == 0:
        # MONDAY PUSH — Upper + Inner Chest Focus
        ex3 = alternate("Hex Press", "Neutral Grip DB Press")
        ex4 = alternate("Skull Crushers", "Overhead Tricep Extension")
        ex5 = alternate("Reverse Grip Tricep Pushdown", "V-Bar Tricep Pushdown")

        split_structure = f"""MONDAY PUSH — UPPER CHEST + INNER CHEST FOCUS. Chest, Triceps, Abs only.

MANDATORY EXERCISE ORDER (fixed positions — do not change):
  Position 1: Flat Barbell Bench Press — sets:4, reps:4-6, weight from working_weights
  Position 2: Incline Barbell Press — sets:4, reps:6-8, weight from working_weights
  Position 3: {ex3} — sets:3, reps:10-12, weight from working_weights (inner chest / neutral grip peak contraction)
  Position 4: {ex4} — sets:3, reps:8-12, weight from working_weights (tricep long head — arm must go overhead)
  Position 5: {ex5} — sets:3, reps:12-15, weight from working_weights (tricep medial/lateral head)
  Position 6: Hanging Leg Raise — sets:3, reps:12-15, bodyweight (lower abs)
  Position 7: Reverse Crunches — sets:3, reps:15-20, bodyweight (lower abs)

CARDIO: Fun LISS after session, 15-20 min, HR 125-135 BPM.
NO shoulder exercises. NO lateral raises. NO rear delt work."""

    elif split == "Push" and today is not None and today.weekday() == 3:
        # THURSDAY PUSH — Overall Chest Focus
        ex3 = cycle3("High-to-Low Cable Fly", "Decline DB Press", "Decline Barbell Press")
        ex4 = alternate("Close Grip Barbell Press", "Tricep Dips")
        ex5 = alternate("Straight Bar Tricep Pushdown", "Rope Tricep Pushdown")

        split_structure = f"""THURSDAY PUSH — OVERALL CHEST FOCUS (Upper + Middle + Lower). Chest, Triceps, Abs only.

MANDATORY EXERCISE ORDER (fixed positions — do not change):
  Position 1: Flat Barbell Bench Press — sets:4, reps:4-6, weight from working_weights (middle chest anchor)
  Position 2: Incline DB Press — sets:4, reps:8-10, weight from working_weights (upper chest)
  Position 3: {ex3} — sets:3, reps:10-15, weight from working_weights (lower chest — this week's rotation)
  Position 4: {ex4} — sets:3, reps:8-12, weight from working_weights (tricep compound — upright torso if dips)
  Position 5: {ex5} — sets:3, reps:12-15, weight from working_weights (tricep lateral head finisher)
  Position 6: Cable Crunch — sets:3, reps:15-20 (upper abs)
  Position 7: Oblique Cable Crunch or Russian Twist — sets:3, reps:15 each side (obliques)

CARDIO: LISS after session, 15-20 min, HR 125-135 BPM.
NO shoulder exercises. NO lateral raises. NO rear delt work."""

    elif split == "Push":
        # Generic Push (fallback if day unknown)
        ex3 = alternate("Hex Press", "Neutral Grip DB Press")
        ex4 = alternate("Skull Crushers", "Overhead Tricep Extension")
        ex5 = alternate("Reverse Grip Tricep Pushdown", "V-Bar Tricep Pushdown")

        split_structure = f"""PUSH DAY — CHEST + TRICEPS + ABS ONLY.

MANDATORY EXERCISE ORDER:
  Position 1: Flat Barbell Bench Press — sets:4, reps:4-6
  Position 2: Incline Barbell Press or Incline DB Press — sets:4, reps:6-8
  Position 3: {ex3} — sets:3, reps:10-12
  Position 4: {ex4} — sets:3, reps:8-12
  Position 5: {ex5} — sets:3, reps:12-15
  Position 6: Hanging Leg Raise — sets:3, reps:12-15 (lower abs)
  Position 7: Reverse Crunches — sets:3, reps:15-20 (lower abs)

CARDIO: LISS 15-20 min, HR 125-135 BPM."""

    elif split == "Pull" and not is_friday_pull:
        # TUESDAY PULL — Lower Back + Mid Back Focus
        ex2 = alternate("Seated Cable Row", "Single Hand Cable Row")
        ex3 = alternate("Straight Arm Pulldown", "Reverse Grip Lat Pulldown")

        split_structure = f"""TUESDAY PULL — LOWER BACK + MID BACK FOCUS. Back, Rear Delt, Biceps, Forearms only.

MANDATORY EXERCISE ORDER (fixed positions — do not change):
  Position 1: Deadlift — sets:4, reps:4-6, weight from working_weights (COMPULSORY — lower back anchor)
  Position 2: {ex2} — sets:4, reps:8-12, weight from working_weights (mid back thickness)
  Position 3: {ex3} — sets:3, reps:12-15, weight from working_weights (lat isolation — cable, no lower back load)
  Position 4: Face Pull — sets:3, reps:15-20, weight from working_weights (rear delt + rotator cuff)
  Position 5: Barbell Curl — sets:3, reps:8-10, weight from working_weights (bicep overall mass — FIXED Tuesday)
  Position 6: Hammer Curl — sets:3, reps:12-15, weight from working_weights (bicep long head + brachialis — FIXED Tuesday)
  Position 7: Barbell Wrist Curl SUPERSET WITH Reverse Wrist Curl — sets:3, reps:15-20 each (forearms — flexors + extensors)

CARDIO: LISS after session, 15-20 min, HR 125-135 BPM.
NO Deadlift alternatives. NO lat pulldown. NO incline curls or preacher curls on Tuesday."""

    elif split == "Pull" and is_friday_pull:
        # FRIDAY PULL — Upper Back + Width Focus (NO DEADLIFT)
        ex2 = alternate("Chest-Supported T-Bar Row", "Neutral Grip Lat Pulldown")
        ex3 = alternate("Barbell Row", "Single Hand DB Row")

        split_structure = f"""FRIDAY PULL — UPPER BACK + WIDTH FOCUS. Back, Rear Delt, Biceps, Forearms only.

⚠️ DEADLIFT BANNED TODAY — Saturday is Legs. Romanian Deadlift already hits hamstrings/lower back on Leg day.

MANDATORY EXERCISE ORDER (fixed positions — do not change):
  Position 1: Lat Pulldown — sets:4, reps:8-12, weight from working_weights (upper back WIDTH anchor — NO DEADLIFT)
  Position 2: {ex2} — sets:4, reps:8-12, weight from working_weights (upper back thickness)
  Position 3: {ex3} — sets:3, reps:8-12, weight from working_weights (back thickness variation)
  Position 4: Reverse Pec Dec — sets:3, reps:15-20, weight from working_weights (rear delt — different from Tuesday)
  Position 5: Incline DB Curl — sets:3, reps:10-12, weight from working_weights (bicep long head peak — FIXED Friday)
  Position 6: Preacher Curl — sets:3, reps:10-12, weight from working_weights (bicep short head width — FIXED Friday)
  Position 7: Reverse Barbell Curl SUPERSET WITH Behind-the-back Wrist Curl — sets:3, reps:12-15 each (forearms — brachioradialis + flexors)

CARDIO: LISS after session, 15-20 min, HR 125-135 BPM.
NO Deadlift. NO Face Pull (used Tuesday — use Reverse Pec Dec instead). NO Barbell Curl or Hammer Curl (Tuesday exercises)."""

    elif split == "Shoulders":
        ex4 = alternate("Face Pull", "Reverse Pec Dec")

        split_structure = f"""WEDNESDAY SHOULDERS — SIDE DELTS + REAR DELTS PRIORITY. Deltoids, Traps only.

MANDATORY EXERCISE ORDER (fixed positions — do not change):
  Position 1: Overhead DB Press — sets:3, reps:10-12, weight from working_weights (overall delt — moderate weight, NOT the priority)
  Position 2: Dumbbell Lateral Raise — sets:4, reps:12-15, weight from working_weights (side delt — PRIORITY, heavier sets)
  Position 3: Leaning Dumbbell Lateral Raise — sets:3, reps:12-15, weight from working_weights (side delt — better angle than standing)
  Position 4: {ex4} — sets:3, reps:15-20, weight from working_weights (rear delt — alternates weekly)
  Position 5: Smith Machine Shrugs — sets:4, reps:10-12, weight from working_weights (traps)
  Position 6: Bent Over Lateral Raise — sets:3, reps:15-20, weight from working_weights (rear delt from different angle)
  Position 7: Cable Rear Delt Fly or Upright Row (wide grip only, pull to nipple height — NOT chin) — sets:3, reps:12-15

CARDIO: 15 min FUN cardio — jumping jacks, cone sprints, skipping, Zumba, or any enjoyable activity. Keep it light and fun.
NO Upright Row with narrow grip (shoulder impingement risk). Side delts are the priority — not OHP."""

    elif split == "Legs":
        ex1 = alternate("Barbell Squat", "Smith Machine Squat")

        split_structure = f"""SATURDAY LEGS — FULL LEG DEVELOPMENT. Quads, Hamstrings, Glutes, Calves only.

MANDATORY EXERCISE ORDER (fixed positions — do not change):
  Position 1: {ex1} — sets:4, reps:6-8, weight from working_weights (quad + glute anchor)
  Position 2: Leg Press — sets:4, reps:8-12, weight from working_weights (quad + hamstring compound)
  Position 3: Walking Lunges — sets:3, reps:12 each leg, weight from working_weights (quad + glute + balance)
  Position 4: Leg Extension — sets:3, reps:12-15, weight from working_weights (quad isolation)
  Position 5: Leg Curl — sets:3, reps:12-15, weight from working_weights (hamstring isolation)
  Position 6: Sumo Squats — sets:3, reps:12-15, weight from working_weights (inner thigh + glutes)
  Position 7: Calf Raises — sets:4, reps:15-20, weight from working_weights (calves — hold peak contraction 1 sec)

CARDIO: LISS after session, 10 min only (legs are taxing enough), HR 120-130 BPM."""

    else:
        split_structure = f"{split.upper()} DAY — Follow compound before isolation ordering."

    prompt = f"""You are an expert personal trainer for an ADVANCED gym-goer (3+ years, machines + free weights).

TODAY'S SPLIT: {split}{' [FRIDAY PULL — NO DEADLIFT]' if is_friday_pull else ''}
SESSION NUMBER FOR THIS SPLIT: {split_count + 1}

WORKING WEIGHTS (use these EXACTLY — do not change any weight value):
{json.dumps(working_weights, indent=2)}

RECENT HISTORY FOR THIS SPLIT (for context and variation reference):
{history_summary}

{split_structure}

UNIVERSAL RULES:
1. Generate EXACTLY 7 exercises — positions 1-7 as defined above.
2. Use working_kg values EXACTLY as provided. Do not modify any weight.
3. Follow the exercise order STRICTLY — do not reorder positions.
4. For fixed exercises (marked FIXED or COMPULSORY) — use that exact exercise, no substitutions.
5. For positions showing a specific exercise already chosen above — use exactly that exercise.
6. Supersets: forearm exercises at position 7 on Pull days are always supersets. Add 1 more superset on an isolation exercise (positions 4-6). Total supersets per session: 2.
7. Dropset: add 1 dropset on one isolation exercise (positions 4-6). Never on position 1-2 compounds.
8. Rep ranges: use the ranges specified per position above.
9. Compound barbell lifts (Bench Press, Deadlift, Squat, OHP, Barbell Row): alternative = null.
10. Machine/cable/isolation exercises: provide 1 alternative targeting same muscle.
11. Add coaching note for technically demanding exercises.
12. NO DUPLICATES — do not repeat the same movement pattern twice in one session.

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
alternative = "Alt: Exercise Name (muscle)" for isolation/cable/machine, null for barbell compounds

Generate the {split} workout now:"""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.5,
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
    """Return last 2 sessions of the same split with exercise names."""
    same = [h for h in history if h.get("split") == split][-2:]
    if not same:
        return "No previous sessions for this split yet."
    return "\n".join(
        f"Date: {s.get('date')} | Exercises: {s.get('exercise_names', 'N/A')}"
        for s in same
    )
