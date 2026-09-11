#!/usr/bin/env python3
"""
Google Sheets QC Automation
============================

Watches a Google Sheet for new call-recording links (column P: "ISA Recording")
and, for any row that has a link but no QC result yet (column AB empty),
downloads the recording, transcribes it, runs it against the 11-point
checklist, and writes the verdict back into the sheet.

Setup:
  pip3 install gspread google-auth requests --break-system-packages

  1. Enable the Google Sheets API in Google Cloud Console.
  2. Create a Service Account, download its JSON key file.
  3. Share your Google Sheet with the service account's email (Editor access).
  4. Fill in the CONFIG section below.

Usage:
  python3 sheet_qc_automation.py            # runs once, processes all new rows
  python3 sheet_qc_automation.py --watch    # loops forever, checks every N seconds
"""

import os
import re
import sys
import time
import argparse
import tempfile

import requests
import gspread
from google.oauth2.service_account import Credentials

# reuse your existing pipeline
from qc_verify import transcribe_call, run_qc_check

# ---------------------------------------------------------------------------
# CONFIG — fill these in
# ---------------------------------------------------------------------------

SERVICE_ACCOUNT_JSON = "service_account.json"   # path to your downloaded key
SHEET_ID = "1VLXdFh3XUD67kKZjYuDoNJ-9BB377gB4oiHr_RwD8zM"  # from the sheet URL
TAB_NAME = "Appointment Tracker"

# Column letters as seen in your sheet
COL_RECORDING = "P"      # ISA Recording (link)
COL_QC_RESULT = "AB"     # QC Results
COL_QC_NOTES = "AC"      # Bad Lead Notes — lists which specific items are missing/failed
COL_ALL_ANSWERS = "AE"   # All 11 checklist answers, one per line

# Threshold: fraction of checklist items that must be "met" to pass
PASS_THRESHOLD = 0.75  # 75%

# If True: any item marked "met_but_disqualifying" forces a fail,
# regardless of overall percentage (e.g. roof under 5 yrs old).
# If False: it's just counted as a miss like any other item.
DISQUALIFYING_ITEMS_FORCE_FAIL = True

POLL_SECONDS = 60  # how often to check for new rows in --watch mode

# ---------------------------------------------------------------------------


HYPERLINK_RE = re.compile(r'=HYPERLINK\(\s*"([^"]+)"', re.IGNORECASE)


def extract_url(display_value: str, formula_value: str) -> str:
    """
    Returns the real URL for a cell that might be:
      - a plain URL typed directly into the cell, or
      - a =HYPERLINK("url", "Download MP")-style formula, where the
        plain display value is just the link text ("Download MP"),
        not the URL itself.
    """
    if formula_value:
        match = HYPERLINK_RE.search(formula_value)
        if match:
            return match.group(1).strip()

    if display_value and display_value.strip().lower().startswith("http"):
        return display_value.strip()

    return ""


def col_to_index(col_letters: str) -> int:
    """Converts a column letter like 'AB' to a 1-based index."""
    index = 0
    for ch in col_letters:
        index = index * 26 + (ord(ch.upper()) - ord("A") + 1)
    return index


def get_worksheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_JSON, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID)
    return sheet.worksheet(TAB_NAME)


def download_recording(url: str) -> str:
    """Downloads an audio file from a URL to a temp file, returns local path."""
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    suffix = ".mp3"
    for ext in (".mp3", ".wav", ".m4a"):
        if url.lower().endswith(ext):
            suffix = ext
            break

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


def format_missing_items(qc_result: dict) -> str:
    """
    Returns a short list of exactly which checklist items were not met,
    e.g. '#4 Roof age [met_but_disqualifying]: 3 years old | #7 Active
    insurance [not_met]: not confirmed'. Empty string if everything passed.
    """
    results = qc_result.get("results", [])
    missing = [r for r in results if r.get("status") != "met"]
    if not missing:
        return "All 11 items met."

    parts = []
    for r in missing:
        item_id = r.get("id", "?")
        item_text = r.get("item", "")
        status = r.get("status", "unknown")
        evidence = r.get("evidence", "not found")
        parts.append(f"#{item_id} {item_text} [{status}]: {evidence}")
    return " | ".join(parts)


def format_all_answers(qc_result: dict) -> str:
    """
    Returns all 11 checklist items with their evidence/status, one per line,
    for the full Q&A record column.
    """
    results = qc_result.get("results", [])
    lines = []
    for r in results:
        item_id = r.get("id", "?")
        item_text = r.get("item", "")
        status = r.get("status", "unknown")
        evidence = r.get("evidence", "not found")
        lines.append(f"{item_id}. {item_text} — {evidence} [{status}]")
    return "\n".join(lines)


def score_qc_result(qc_result: dict) -> tuple[bool, float, str]:
    """
    Returns (passed, percent_met, reason_string) based on the checklist results
    and PASS_THRESHOLD / DISQUALIFYING_ITEMS_FORCE_FAIL settings.
    """
    results = qc_result.get("results", [])
    if not results:
        return False, 0.0, "No checklist results returned."

    total = len(results)
    met_count = sum(1 for r in results if r.get("status") == "met")
    disqualifying_hits = [r for r in results if r.get("status") == "met_but_disqualifying"]

    percent_met = met_count / total

    if DISQUALIFYING_ITEMS_FORCE_FAIL and disqualifying_hits:
        items = ", ".join(str(r.get("id")) for r in disqualifying_hits)
        return False, percent_met, f"Disqualifying item(s) hit: #{items}"

    passed = percent_met >= PASS_THRESHOLD
    reason = qc_result.get("verdict_reason", "")
    return passed, percent_met, reason


def process_row(ws, row_num: int, recording_url: str):
    print(f"  Row {row_num}: processing {recording_url}")

    audio_path = None
    try:
        audio_path = download_recording(recording_url)
        transcript = transcribe_call(audio_path)
        qc_result = run_qc_check(transcript)

        passed, percent_met, reason = score_qc_result(qc_result)
        verdict_label = "QC - Valid" if passed else "QC - Failed"

        ws.update_acell(f"{COL_QC_RESULT}{row_num}", verdict_label)

        missing_text = format_missing_items(qc_result)
        note = f"{percent_met:.0%} checklist met. {missing_text}".strip()
        ws.update_acell(f"{COL_QC_NOTES}{row_num}", note)

        all_answers_text = format_all_answers(qc_result)
        ws.update_acell(f"{COL_ALL_ANSWERS}{row_num}", all_answers_text)

        print(f"    -> {verdict_label} ({percent_met:.0%} met) — {reason}")

    except Exception as e:
        ws.update_acell(f"{COL_QC_RESULT}{row_num}", "QC - Error")
        ws.update_acell(f"{COL_QC_NOTES}{row_num}", f"Automation error: {e}")
        print(f"    ERROR: {e}")

    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


def run_once(start_row: int = 2):
    ws = get_worksheet()
    all_values = ws.get_all_values()
    all_formulas = ws.get_all_values(value_render_option="FORMULA")

    rec_idx = col_to_index(COL_RECORDING) - 1
    result_idx = col_to_index(COL_QC_RESULT) - 1

    new_rows = []
    for i, row in enumerate(all_values):
        row_num = i + 1  # 1-based, matches sheet row numbers
        if row_num < max(start_row, 2):
            continue  # header row, or before the requested start row

        display_val = row[rec_idx].strip() if len(row) > rec_idx else ""
        formula_row = all_formulas[i] if i < len(all_formulas) else []
        formula_val = formula_row[rec_idx].strip() if len(formula_row) > rec_idx else ""

        existing_result = row[result_idx].strip() if len(row) > result_idx else ""

        recording_url = extract_url(display_val, formula_val)

        if recording_url and not existing_result:
            new_rows.append((row_num, recording_url))

    if not new_rows:
        print("No new rows to process.")
        return

    print(f"Found {len(new_rows)} new row(s) to process.")
    for row_num, recording_url in new_rows:
        process_row(ws, row_num, recording_url)


def main():
    parser = argparse.ArgumentParser(description="Google Sheets QC automation.")
    parser.add_argument("--watch", action="store_true", help="Run continuously, polling for new rows")
    parser.add_argument("--start-row", type=int, default=2, help="Only process rows at or after this row number")
    args = parser.parse_args()

    if args.watch:
        print(f"Watching sheet every {POLL_SECONDS}s. Ctrl+C to stop.")
        while True:
            try:
                run_once(start_row=args.start_row)
            except Exception as e:
                print(f"ERROR during poll: {e}")
            time.sleep(POLL_SECONDS)
    else:
        run_once(start_row=args.start_row)


if __name__ == "__main__":
    main()