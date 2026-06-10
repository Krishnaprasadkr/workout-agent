import os
import json
from datetime import date
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = "WorkoutHistory"

# Colours (RGB as floats 0-1)
HEADER_BG    = {"red": 0.18, "green": 0.18, "blue": 0.18}   # dark charcoal
HEADER_FG    = {"red": 1.0,  "green": 1.0,  "blue": 1.0}    # white text
ROW_ODD_BG   = {"red": 1.0,  "green": 1.0,  "blue": 1.0}    # white
ROW_EVEN_BG  = {"red": 0.93, "green": 0.95, "blue": 1.0}    # light blue-grey

SPLIT_COLORS = {
    "Push":      {"red": 1.0,  "green": 0.87, "blue": 0.80},  # warm peach
    "Pull":      {"red": 0.80, "green": 0.93, "blue": 1.0},   # light blue
    "Legs":      {"red": 0.82, "green": 0.96, "blue": 0.82},  # light green
    "Shoulders": {"red": 0.96, "green": 0.90, "blue": 1.0},   # light purple
    "Rest":      {"red": 0.95, "green": 0.95, "blue": 0.95},  # light grey
}

# Column widths in pixels
COL_WIDTHS = [110, 100, 420, 130, 120, 200]


def _get_service():
    creds_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


def _get_sheet_id(service):
    """Get the numeric sheet ID for SHEET_NAME."""
    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == SHEET_NAME:
            return s["properties"]["sheetId"]
    raise ValueError(f"Sheet '{SHEET_NAME}' not found.")


def get_history():
    """Read all rows and return as list of dicts."""
    service = _get_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:F")
        .execute()
    )
    rows = result.get("values", [])
    if len(rows) <= 1:
        return []
    headers = rows[0]
    history = []
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        history.append(dict(zip(headers, padded)))
    return history


def log_session(today: date, split: str, workout_plan: dict):
    """Append today's session and reformat the sheet."""
    service = _get_service()
    sheet_id = _get_sheet_id(service)

    exercise_names = ", ".join(
        ex["name"] for ex in workout_plan.get("exercises", [])
    )

    # Calculate total volume
    total_volume = 0
    for ex in workout_plan.get("exercises", []):
        reps_str = str(ex.get("reps", "0"))
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
        json.dumps(workout_plan),
    ]

    # 1. Append the new row
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:F",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    print(f"Session logged: {split} on {today}")

    # 2. Re-apply formatting to the whole sheet
    _format_sheet(service, sheet_id)


def _format_sheet(service, sheet_id: int):
    """Apply full formatting: header style, column widths, alternating rows, split colours."""

    # Get current row count
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:A")
        .execute()
    )
    total_rows = len(result.get("values", [])) + 1  # +1 buffer

    requests = []

    # ── 1. Column widths ───────────────────────────────────────────────────────
    for i, width in enumerate(COL_WIDTHS):
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": i,
                    "endIndex": i + 1,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })

    # ── 2. Header row — dark background, white bold text, freeze ──────────────
    requests.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": HEADER_BG,
                    "textFormat": {
                        "foregroundColor": HEADER_FG,
                        "bold": True,
                        "fontSize": 10,
                    },
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }
    })

    # Freeze header row
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # ── 3. Alternating row colours for data rows ───────────────────────────────
    for row_idx in range(1, total_rows):
        bg = ROW_ODD_BG if row_idx % 2 == 1 else ROW_EVEN_BG
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_idx,
                    "endRowIndex": row_idx + 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 6,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": bg,
                        "textFormat": {"fontSize": 9},
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
            }
        })

    # ── 4. Split colour on column B (split name) ───────────────────────────────
    # Read split values to colour each row
    split_result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B2:B{total_rows}")
        .execute()
    )
    split_values = split_result.get("values", [])
    for i, sv in enumerate(split_values):
        split_name = sv[0] if sv else ""
        color = SPLIT_COLORS.get(split_name, ROW_ODD_BG)
        row_idx = i + 1  # offset for header
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row_idx,
                    "endRowIndex": row_idx + 1,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": color,
                        "textFormat": {"bold": True, "fontSize": 9},
                        "horizontalAlignment": "CENTER",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }
        })

    # ── 5. Border on entire data range ─────────────────────────────────────────
    border_style = {
        "style": "SOLID",
        "color": {"red": 0.75, "green": 0.75, "blue": 0.75},
    }
    requests.append({
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": total_rows,
                "startColumnIndex": 0,
                "endColumnIndex": 6,
            },
            "innerHorizontal": border_style,
            "innerVertical": border_style,
            "bottom": border_style,
            "right": border_style,
        }
    })

    # ── 6. Wrap text in exercise_names column (C) ──────────────────────────────
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": total_rows,
                "startColumnIndex": 2,
                "endColumnIndex": 3,
            },
            "cell": {
                "userEnteredFormat": {"wrapStrategy": "WRAP"}
            },
            "fields": "userEnteredFormat.wrapStrategy",
        }
    })

    # ── Execute all formatting requests in one batch ───────────────────────────
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()
    print("Sheet formatting applied.")


def ensure_sheet_headers():
    """Create header row and apply initial formatting. Run once during setup."""
    service = _get_service()
    sheet_id = _get_sheet_id(service)

    headers = [["📅 Date", "💪 Split", "🏋️ Exercises", "📊 Volume (kg)", "# Exercises", "Full Plan JSON"]]
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        body={"values": headers},
    ).execute()

    _format_sheet(service, sheet_id)
    print("Sheet headers created and formatted.")


if __name__ == "__main__":
    ensure_sheet_headers()
