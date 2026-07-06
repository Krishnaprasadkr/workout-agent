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
    """
    Insert today's session into the sessions table.
    If a session for this user + date already exists, UPDATE it instead
    of inserting a duplicate (e.g. manual test run + scheduled run same day).
    """

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

    # Check if a session already exists for this user + date
    existing = (
        _client.table("sessions")
        .select("id")
        .eq("user_id", USER_ID)
        .eq("date", str(today))
        .execute()
    )

    if existing.data:
        # Update the existing row instead of creating a duplicate
        session_id = existing.data[0]["id"]
        _client.table("sessions").update(row).eq("id", session_id).execute()
        print(f"Session UPDATED (already existed today) to Supabase: {split} on {today}")
    else:
        _client.table("sessions").insert(row).execute()
        print(f"Session INSERTED to Supabase: {split} on {today}")


def get_actuals_history():
    """
    Fetch the most recent actual workout entry per exercise name.
    Used to show 'Last session: 4 × 8 @ 50kg' in the Telegram message.

    Returns a dict keyed by exercise_name:
    {
      "Flat Barbell Bench Press": {
          "actual_sets": 4,
          "actual_reps": "8",
          "actual_weight_kg": 50.0,
          "date": "2026-06-30",
          "is_actual": True   # True = real logged data, False = planned fallback
      },
      ...
    }
    """
    # Step 1 — fetch all actual workout rows for this user (excluding skip markers)
    result = (
        _client.table("actual_workouts")
        .select("exercise_name, actual_sets, actual_reps, actual_weight_kg, date")
        .eq("user_id", USER_ID)
        .eq("skipped", False)
        .neq("exercise_name", "__day_skipped__")
        .not_.is_("actual_weight_kg", "null")
        .order("date", desc=False)
        .execute()
    )
    rows = result.data or []

    # Keep only the most recent entry per exercise
    best_actual = {}
    for r in rows:
        ex = r.get("exercise_name")
        if ex:
            best_actual[ex] = {
                "actual_sets":      r.get("actual_sets"),
                "actual_reps":      r.get("actual_reps"),
                "actual_weight_kg": r.get("actual_weight_kg"),
                "date":             str(r.get("date")),
                "is_actual":        True,
            }

    # Step 2 — for any exercise NOT in actual_workouts, fall back to
    # most recent planned weight from the sessions table's full_plan_json
    sessions_result = (
        _client.table("sessions")
        .select("date, full_plan_json")
        .eq("user_id", USER_ID)
        .order("date", desc=False)
        .execute()
    )
    for s in (sessions_result.data or []):
        plan = s.get("full_plan_json") or {}
        for ex in plan.get("exercises", []):
            name = ex.get("name")
            if name and name not in best_actual:
                # Only add as fallback if not already covered by actual data
                best_actual[name] = {
                    "actual_sets":      ex.get("sets"),
                    "actual_reps":      str(ex.get("reps", "")),
                    "actual_weight_kg": ex.get("weight_kg"),
                    "date":             str(s.get("date")),
                    "is_actual":        False,  # this is planned, not actual
                }

    print(f"[Supabase] Loaded last session data for {len(best_actual)} exercises.")
    return best_actual
