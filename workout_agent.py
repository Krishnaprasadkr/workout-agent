import os
import json
from datetime import datetime, date
from zoneinfo import ZoneInfo
import sheets_helper
import telegram_helper
import gemini_helper

IST = ZoneInfo("Asia/Kolkata")

# ── Split rotation ────────────────────────────────────────────────────────────
SPLIT_ORDER = ["Push", "Pull", "Legs", "Push", "Pull", "Shoulders", "Rest"]

# ── Baseline strength profile (your current maxes) ───────────────────────────
BASELINE = {
    "Push": [
        {"name": "Flat Barbell Bench Press", "max_kg": 70, "max_reps": 6, "muscle": "Chest"},
        {"name": "Incline Dumbbell Press",   "max_kg": 20, "max_reps": 9, "muscle": "Upper Chest"},
        {"name": "Pec Dec Fly",              "max_kg": 40, "max_reps": 8, "muscle": "Chest"},
        {"name": "Overhead Tricep Extension","max_kg": 17.5,"max_reps": 8,"muscle": "Triceps"},
        {"name": "Tricep Pushdown",          "max_kg": 35, "max_reps": 9, "muscle": "Triceps"},
    ],
    "Pull": [
        {"name": "Deadlift",                 "max_kg": 90, "max_reps": 1, "muscle": "Back / Hamstrings"},
        {"name": "Lat Pulldown",             "max_kg": 45, "max_reps": 9, "muscle": "Lats"},
        {"name": "Seated Cable Row",         "max_kg": 80, "max_reps": 11,"muscle": "Mid Back"},
        {"name": "Face Pulls",               "max_kg": 35, "max_reps": 10,"muscle": "Rear Delt / Rotator Cuff"},
        {"name": "Barbell Curl",             "max_kg": 35, "max_reps": 8, "muscle": "Biceps"},
        {"name": "Hammer Curl",              "max_kg": 12.5,"max_reps":15,"muscle": "Brachialis / Forearms"},
    ],
    "Legs": [
        {"name": "Barbell Squat",            "max_kg": 70, "max_reps": 8, "muscle": "Quads / Glutes"},
        {"name": "Leg Press",                "max_kg": 140,"max_reps": 7, "muscle": "Quads / Hamstrings"},
        {"name": "Romanian Deadlift (DB)",   "max_kg": 17.5,"max_reps": 9,"muscle": "Hamstrings / Glutes"},
        {"name": "Leg Curl",                 "max_kg": 45, "max_reps": 9, "muscle": "Hamstrings"},
        {"name": "Calf Raises",              "max_kg": 25, "max_reps": 20,"muscle": "Calves"},
    ],
    "Shoulders": [
        {"name": "Overhead Press (DB)",      "max_kg": 15, "max_reps": 10,"muscle": "Shoulders (overall)"},
        {"name": "Lateral Raises",           "max_kg": 7.5,"max_reps": 12,"muscle": "Side Delts"},
        {"name": "Reverse Pec Dec",          "max_kg": 30, "max_reps": 11,"muscle": "Rear Delts"},
        {"name": "Smith Machine Shrugs",     "max_kg": 80, "max_reps": 8, "muscle": "Traps"},
    ],
}

def main():
    today = datetime.now(IST).date()
    print(f"[{today}] Workout Agent starting... (IST timezone)")

    # 1. Read history from Google Sheets
    history = sheets_helper.get_history()
    print(f"Loaded {len(history)} past sessions from Sheets.")

    # 2. Determine today's split
    split = determine_split(history, today)
    print(f"Today's split: {split}")

    if split == "Rest":
        msg = build_rest_message(today)
        telegram_helper.send(msg)
        print("Rest day message sent.")
        return

    # 3. Get current working weights (with progressive overload applied)
    working_weights = compute_working_weights(split, history)

    # 4. Ask Gemini to build the structured workout plan
    workout_plan = gemini_helper.generate_workout(split, working_weights, history)

    # 5. Log today's session to Sheets
    sheets_helper.log_session(today, split, workout_plan)

    # 6. Build and send Telegram message
    msg = build_workout_message(today, split, workout_plan)
    telegram_helper.send(msg)
    print("Workout message sent successfully.")

    # 7. If Sunday, send weekly summary
    if today.weekday() == 6:
        summary = gemini_helper.generate_weekly_summary(history)
        telegram_helper.send(summary)
        print("Weekly summary sent.")

def determine_split(history, today):
    """Determine today's split based on last session in history."""
    if not history:
        return SPLIT_ORDER[0]
    last_split = history[-1].get("split", "Rest")
    if last_split == "Rest":
        last_idx = SPLIT_ORDER.index("Rest")
    else:
        try:
            last_idx = SPLIT_ORDER.index(last_split)
        except ValueError:
            last_idx = -1
    next_idx = (last_idx + 1) % len(SPLIT_ORDER)
    return SPLIT_ORDER[next_idx]

def compute_working_weights(split, history):
    """
    Apply progressive overload:
    - Compounds: +2.5kg every 2 sessions of same split
    - Isolations: +1kg every 2 sessions of same split
    """
    exercises = BASELINE.get(split, [])
    # Count how many times this split has been done
    split_count = sum(1 for h in history if h.get("split") == split)

    COMPOUND = ["Barbell", "Deadlift", "Squat", "Press", "Row", "Pulldown"]

    result = []
    for ex in exercises:
        is_compound = any(c.lower() in ex["name"].lower() for c in COMPOUND)
        increment = 2.5 if is_compound else 1.0
        overload_cycles = split_count // 2
        working_weight = ex["max_kg"] * 0.70 + (overload_cycles * increment)
        result.append({
            **ex,
            "working_kg": round(working_weight * 2) / 2,  # round to nearest 0.5kg
            "overload_cycles": overload_cycles,
        })
    return result

def build_workout_message(today, split, workout_plan):
    day_name = today.strftime("%A, %d %b %Y")
    lines = [
        f"💪 *Daily Workout — {split.upper()}*",
        f"📅 {day_name}",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for i, ex in enumerate(workout_plan.get("exercises", []), 1):
        tag = ""
        if ex.get("type") == "superset":
            tag = " ⚡ SUPERSET"
        elif ex.get("type") == "dropset":
            tag = " 🔽 DROPSET"

        lines.append(f"\n*{i}. {ex['name']}*{tag}")
        lines.append(f"   🎯 Muscle: {ex['muscle']}")
        lines.append(f"   📊 Sets × Reps: {ex['sets']} × {ex['reps']}")
        lines.append(f"   🏋️ Weight: {ex['weight_kg']}kg")
        if ex.get("partner"):
            lines.append(f"   ↪️ With: {ex['partner']}")
        if ex.get("alternative"):
            lines.append(f"   🔄 If occupied: {ex['alternative']}")
        if ex.get("note"):
            lines.append(f"   💡 {ex['note']}")

    # Cardio finisher
    cardio = workout_plan.get("cardio", {})
    if cardio:
        lines += [
            "\n━━━━━━━━━━━━━━━━━━━━━━",
            "🏃 *Cardio Finisher (Fat Loss)*",
            f"   {cardio.get('exercise', 'Treadmill Walk')}",
            f"   ⏱ Duration: {cardio.get('duration', '20 min')}",
            f"   ❤️ HR Target: {cardio.get('hr_target', '125–135 BPM')}",
            f"   💡 {cardio.get('note', 'Keep it steady, breathe easy.')}",
        ]

    lines += [
        "\n━━━━━━━━━━━━━━━━━━━━━━",
        "🔥 *Train hard. Stay consistent.*",
    ]
    return "\n".join(lines)

def build_rest_message(today):
    day_name = today.strftime("%A, %d %b %Y")
    return (
        f"😴 *Rest Day — {day_name}*\n\n"
        "Your body grows when you rest, not just when you train.\n\n"
        "✅ Stay hydrated\n"
        "✅ Get 7–8 hours of sleep\n"
        "✅ Optional: 30 min easy walk\n\n"
        "💪 Come back stronger tomorrow."
    )

if __name__ == "__main__":
    main()
