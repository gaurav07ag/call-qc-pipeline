# Call-qc-pipeline System

Automatically transcribes call recordings and checks them against your
11-point qualification script, marking each call **QC_VALID** or
**QC_NOT_VALID** with evidence for every checklist item...

## 1. Setup

```bash
pip install -r requirements.txt
```

Get API keys:
- **AssemblyAI** (transcription + speaker labels): https://www.assemblyai.com/
  Free tier available; paid usage is roughly $0.12–0.27 per call hour.
- **Anthropic** (QC verification): https://console.anthropic.com/
  You already have this if you're using Claude.

Set them as environment variables:

```bash
export ASSEMBLYAI_API_KEY="your_key_here"
export ANTHROPIC_API_KEY="your_key_here"
```

(On Windows, use `set ASSEMBLYAI_API_KEY=your_key_here` in Command Prompt,
or add them in System Environment Variables.)

## 2. Run it

**Single call:**
```bash
python qc_verify.py path/to/Barbara.mp3
```

**Batch — a whole folder of recordings:**
```bash
python qc_verify.py path/to/recordings_folder/
```

## 3. What you get

- `qc_results/<call_name>.json` — full transcript + per-question breakdown
  for that call
- `qc_results/qc_log.csv` — one row per call with verdict, reason, and
  which items need human review. Open this in Excel/Google Sheets and
  filter by verdict to focus your QC team's time.

## 4. Editing the checklist

Open `qc_checklist.py`. Each item has:
- `item` — the question/requirement in plain English
- `guidance` — extra instruction telling the AI exactly what counts as "met"

Add, remove, or reword items here — you don't need to touch `qc_verify.py`.
Currently all 11 items are treated as mandatory (every item must be "met"
for a QC_VALID verdict), matching your script.

## 5. Human-in-the-loop review

Any checklist item the AI marks `unclear` or low-confidence is listed in
the `items_needing_human_review` column of the CSV. Route those calls to
your QC team for manual sign-off rather than trusting the AI verdict blindly
— this also gives you a feedback loop: if the AI is consistently unsure
about the same item, the checklist wording probably needs tightening.

## 6. Notes on accuracy

- The AI identifies which speaker is the agent vs. the homeowner from
  conversation context (AssemblyAI doesn't know roles in advance). Spot-check
  this on your first batch of calls to confirm it's getting it right.
- Roof age (item 4) has a business rule built in: if asked but the roof is
  under 5 years old, it's marked `met_but_disqualifying` rather than
  `not_met` — the question was asked correctly, but the lead doesn't qualify.
  You can adjust this logic in `qc_checklist.py`'s guidance text.
- Cost per call: AssemblyAI transcription (~$0.01–0.02 for a 3-5 min call)
  + one Claude API call (~$0.01–0.03 depending on transcript length).
  At under 100 calls/day this is a few dollars a day total.

## 7. Next steps to productionize

- Point the script at wherever your recordings land automatically (a
  watched folder, S3 bucket, or your dialer's webhook) instead of running
  it manually.
- Swap the CSV log for a proper database or push results into your CRM.
- Add a simple dashboard (Airtable, Retool, or a small web app) so the QC
  team doesn't have to open CSV/JSON files directly.
