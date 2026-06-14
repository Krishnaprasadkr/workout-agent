import os
import re
import json
from datetime import date
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"].strip().rstrip("/")
# Defensive: remove accidental /rest/v1 suffix — the client appends this itself
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[: -len("/rest/v1")]
SUPABASE_KEY = os.environ["SUPABASE_KEY"].strip()
USER_ID = os.environ["SUPABASE_USER_ID"].strip()

print(f"[Supabase] Connecting to: {SUPABASE_URL}")
print(f"[Supabase] User ID: {USER_ID}")

_client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_history():
    """
    Read all past sessions for this user, ordered by date.
    Returns a list of dicts with the same shape as the old Sheets version:
    date, split, exercise_names, total_volume_kg, exercise_count, full_plan_json
    """
    result = (
        _client.table("sessions")
        .select("date, split, exercise_names, total_volume_kg, exercise_count, full_plan_json")
        .eq("user_id", USER_ID)
        .order("date", desc=False)
        .execute()
    )
    rows = result.data or []

    # Keep return shape identical to old Sheets helper (string values where needed)
    history = []
    for r in rows:
        history.append({
            "date": str(r.get("date")),
            "split": r.get("split"),
            "exercise_names": r.get("exercise_names"),
            "total_volume_kg": r.get("total_volume_kg"),
            "exercise_count": r.get("exercise_count"),
            "full_plan_json": json.dumps(r.get("full_plan_json")) if r.get("full_plan_json") else "",
        })
    return history


def log_session(today: date, split: str, workout_plan: dict):
    """Insert today's session into the sessions table."""

    exercise_names = ", ".join(
        ex["name"] for ex in workout_plan.get("exercises", [])
    )

    # Calculate total volume — handles reps like "8-10", "12", "12 per leg"
    total_volume = 0
    for ex in workout_plan.get("exercises", []):
        reps_str = str(ex.get("reps", "0"))
        numbers = re.findall(r'\d+', reps_str)
        if numbers:
            reps_mid = sum(int(n) for n in numbers) / len(numbers)
        else:
            reps_mid = 10
        total_volume += (ex.get("sets") or 0) * reps_mid * (ex.get("weight_kg") or 0)

    row = {
        "user_id": USER_ID,
        "date": str(today),
        "split": split,
        "exercise_names": exercise_names,
        "total_volume_kg": round(total_volume),
        "exercise_count": len(workout_plan.get("exercises", [])),
        "full_plan_json": workout_plan,  # JSONB column — pass dict directly
    }

    _client.table("sessions").insert(row).execute()
    print(f"Session logged to Supabase: {split} on {today}")
