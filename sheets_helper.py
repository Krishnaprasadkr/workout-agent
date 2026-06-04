import os
import json
from datetime import date
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = "WorkoutHistory"

def _get_service():
    creds_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)

def get_history():
    """Read all rows from WorkoutHistory sheet and return as list of dicts."""
    service = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:F")
        .execute()
    )
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []  # Only header or empty

    headers = rows[0]
    history = []
    for row in rows[1:]:
        # Pad row if shorter than headers
        padded = row + [""] * (len(headers) - len(row))
        history.append(dict(zip(headers, padded)))
    return history

def log_session(today: date, split: str, workout_plan: dict):
    """Append today's session as a new row in the sheet."""
    service = _get_service()

    exercise_names = ", ".join(
        ex["name"] for ex in workout_plan.get("exercises", [])
    )
    # Calculate rough total volume: sets × reps_midpoint × weight
    total_volume = 0
    for ex in workout_plan.get("exercises", []):
        reps_str = str(ex.get("reps", "0"))
        # Handle ranges like "8-10" → use midpoint
        if "-" in reps_str:
            parts = reps_str.split("-")
            reps_mid = (int(parts[0]) + int(parts[1])) / 2
        else:
            reps_mid = float(reps_str)
        total_volume += ex.get("sets", 0) * reps_mid * ex.get("weight_kg", 0)

    row = [
        str(today),
        split,
        exercise_names,
        round(total_volume),
        len(workout_plan.get("exercises", [])),
        json.dumps(workout_plan),  # full plan stored as JSON string
    ]

    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:F",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    print(f"Session logged to Sheets: {split} on {today}")

def ensure_sheet_headers():
    """Create header row if sheet is empty. Run once during setup."""
    service = _get_service()
    headers = [["date", "split", "exercise_names", "total_volume_kg", "exercise_count", "full_plan_json"]]
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        body={"values": headers},
    ).execute()
    print("Sheet headers created.")

if __name__ == "__main__":
    ensure_sheet_headers()
