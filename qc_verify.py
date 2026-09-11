#!/usr/bin/env python3
"""
Automated QC Verification Pipeline for Roofing Lead-Gen Calls
================================================================

What it does:
  1. Takes a call recording (mp3/wav/etc.)
  2. Transcribes it with speaker labels (Agent vs Homeowner) via AssemblyAI
  3. Sends the transcript + QC checklist to Gemini for structured verification
  4. Outputs a QC_VALID / QC_NOT_VALID verdict with per-question evidence
  5. Appends the result to a running CSV log for the QC team to review

Setup:
  pip3 install assemblyai google-genai --break-system-packages

  export ASSEMBLYAI_API_KEY="your_assemblyai_key_here"
  export GEMINI_API_KEY="your_gemini_key_here"

Usage:
  python qc_verify.py path/to/call.mp3
  python qc_verify.py path/to/folder_of_calls/          # batch mode

Output:
  - One JSON file per call in ./qc_results/<call_name>.json
  - One row appended to ./qc_results/qc_log.csv
"""

import os
import sys
import json
import csv
import time
import argparse
from pathlib import Path
from datetime import datetime

import assemblyai as aai
from google import genai

from qc_checklist import CHECKLIST

RESULTS_DIR = Path("qc_results")
LOG_CSV = RESULTS_DIR / "qc_log.csv"
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}

GEMINI_MODEL = "gemini-3.5-flash-lite"


# ---------------------------------------------------------------------------
# Step 1: Transcription with speaker diarization
# ---------------------------------------------------------------------------

def transcribe_call(audio_path: str) -> str:
    """
    Transcribes an audio file with speaker labels using AssemblyAI.
    Returns a formatted transcript string like:
        Speaker A: Hi, is this Barbara?
        Speaker B: Yes, speaking.
    """
    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ASSEMBLYAI_API_KEY not set. Get one at https://www.assemblyai.com/"
        )
    aai.settings.api_key = api_key

    config = aai.TranscriptionConfig(speaker_labels=True)
    transcriber = aai.Transcriber(config=config)

    print(f"  Transcribing {audio_path} ...")
    transcript = transcriber.transcribe(audio_path)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"Transcription failed: {transcript.error}")

    lines = []
    for utt in transcript.utterances:
        lines.append(f"Speaker {utt.speaker}: {utt.text}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 2: QC verification via Gemini
# ---------------------------------------------------------------------------

def build_prompt(transcript: str) -> str:
    checklist_text = "\n".join(
        f"{item['id']}. {item['item']}\n   Guidance: {item['guidance']}"
        for item in CHECKLIST
    )

    return f"""You are a QC reviewer for a roofing lead-generation call center.
Agents call homeowners to qualify them and book a roof inspection appointment
with a roofer. Review the transcript below against the checklist and
determine whether each item was properly covered by the AGENT during the call.

Note: speaker labels (Speaker A, Speaker B, etc.) are not pre-assigned to
roles. Use conversational context to determine which speaker is the agent
(asking qualifying questions, offering the appointment) and which is the
homeowner (answering, being qualified).

CHECKLIST (all items are mandatory — every item must be "met" for the call
to pass QC):

{checklist_text}

IMPORTANT: These questions may be asked in ANY order during the call, not
necessarily the order listed above. Agents may also revisit a topic later
in the call (e.g. re-confirm the address after scheduling). Search the
ENTIRE transcript for each item — do not assume sequential order, and do
not penalize an item just because it was covered out of order or combined
with another question in a single sentence.

TRANSCRIPT:
{transcript}

Return ONLY valid JSON (no markdown fences, no preamble) in this exact shape:

{{
  "identified_agent_speaker": "A or B etc.",
  "identified_homeowner_speaker": "A or B etc.",
  "results": [
    {{
      "id": 1,
      "item": "...",
      "status": "met" | "not_met" | "unclear" | "met_but_disqualifying",
      "evidence": "short quote or paraphrase from transcript, or 'not found'",
      "confidence": "high" | "medium" | "low"
    }},
    ... one entry per checklist item ...
  ],
  "overall_verdict": "QC_VALID" | "QC_NOT_VALID",
  "verdict_reason": "one sentence explaining the verdict",
  "items_needing_human_review": [list of item ids with status 'unclear' or low confidence]
}}
"""


def run_qc_check(transcript: str, max_retries: int = 5) -> dict:
    """Sends the transcript to Gemini and returns the parsed QC result.
    Retries automatically on transient server errors (e.g. 503 UNAVAILABLE)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set.")

    client = genai.Client(api_key=api_key)
    prompt = build_prompt(transcript)

    print("  Running QC verification...")

    response = None
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={"http_options": {"timeout": 60000}},  # 60s timeout, in ms
            )
            break  # success
        except genai.errors.ClientError:
            raise  # permanent problems (bad key, bad model name) won't fix themselves — fail fast
        except Exception as e:
            last_error = e
            wait_seconds = min(2 ** attempt, 30)  # 2, 4, 8, 16, 30...
            print(
                f"  Gemini error on attempt {attempt}/{max_retries} "
                f"({type(e).__name__}: {e}), retrying in {wait_seconds}s..."
            )
            time.sleep(wait_seconds)

    if response is None:
        raise RuntimeError(
            f"Gemini API unavailable after {max_retries} attempts: {last_error}"
        )

    raw_text = (response.text or "").strip()

    # Strip accidental markdown fences just in case
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Could not parse model output as JSON: {e}\nRaw output:\n{raw_text}"
        )


# ---------------------------------------------------------------------------
# Step 3: Save results
# ---------------------------------------------------------------------------

def save_result(call_name: str, transcript: str, qc_result: dict):
    RESULTS_DIR.mkdir(exist_ok=True)

    out = {
        "call_name": call_name,
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "transcript": transcript,
        "qc_result": qc_result,
    }

    json_path = RESULTS_DIR / f"{call_name}.json"
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2)

    # Append summary row to CSV log
    is_new = not LOG_CSV.exists()
    with open(LOG_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow([
                "call_name", "processed_at", "verdict", "reason",
                "items_needing_review", "json_file"
            ])
        writer.writerow([
            call_name,
            out["processed_at"],
            qc_result.get("overall_verdict", "ERROR"),
            qc_result.get("verdict_reason", ""),
            ",".join(str(i) for i in qc_result.get("items_needing_human_review", [])),
            str(json_path),
        ])

    print(f"  Saved: {json_path}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def process_call(audio_path: Path):
    call_name = audio_path.stem
    print(f"\nProcessing: {audio_path.name}")

    transcript = transcribe_call(str(audio_path))
    qc_result = run_qc_check(transcript)
    save_result(call_name, transcript, qc_result)

    verdict = qc_result.get("overall_verdict", "ERROR")
    print(f"  Verdict: {verdict} — {qc_result.get('verdict_reason', '')}")
    return qc_result


def main():
    parser = argparse.ArgumentParser(description="Automated QC verification for call recordings.")
    parser.add_argument("path", help="Path to an audio file or a folder of audio files")
    args = parser.parse_args()

    target = Path(args.path)

    if target.is_dir():
        audio_files = sorted(
            p for p in target.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS
        )
        if not audio_files:
            print("No audio files found in that folder.")
            sys.exit(1)
        for f in audio_files:
            try:
                process_call(f)
            except Exception as e:
                print(f"  ERROR processing {f.name}: {e}")
    elif target.is_file():
        process_call(target)
    else:
        print(f"Path not found: {target}")
        sys.exit(1)

    print(f"\nDone. Results in {RESULTS_DIR}/ (see qc_log.csv for the summary).")


if __name__ == "__main__":
    main()