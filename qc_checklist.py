"""
QC Checklist definition for roofing lead-gen appointment calls.
Edit this file to change what the AI checks for — no need to touch the
transcription or scoring logic in qc_verify.py.
"""

CHECKLIST = [
    {
        "id": 1,
        "item": "Confirmed property owner or decision-maker",
        "guidance": "The homeowner must explicitly confirm they own the property "
                     "or are the decision-maker for repairs.",
    },
    {
        "id": 2,
        "item": "Verified complete property address including ZIP",
        "guidance": "The agent must state the address, and the homeowner must "
                     "confirm it — either by repeating part of it back, or by "
                     "giving a clear affirmative response (e.g. 'yes', 'that's "
                     "correct') to the agent's stated address. A simple 'yes' "
                     "confirmation is sufficient, same standard as item 1.",
    },
    {
        "id": 3,
        "item": "Confirmed best phone number",
        "guidance": "Explicit confirmation of a callback/contact number.",
    },
    {
        "id": 4,
        "item": "Asked roof age, and roof is more than 5 years old",
        "guidance": "Must both ask the age AND the stated age must exceed 5 years "
                     "to be 'met'. If asked but roof is younger than 5 years, mark "
                     "as met_but_disqualifying and note it.",
    },
    {
        "id": 5,
        "item": "Confirmed roof type (shingles, metal, tile, or flat)",
        "guidance": "Homeowner states or confirms one of these roof types.",
    },
    {
        "id": 6,
        "item": "Asked about visible damage, leaking, missing shingles, or other "
                "roof-related concerns, with the homeowner's answer captured",
        "guidance": "The agent asking the question is NOT enough on its own. The "
                     "homeowner must give an actual answer (yes, no, or a "
                     "description of damage) that is captured in the transcript. "
                     "If the agent asks but the homeowner's response is missing, "
                     "inaudible, or never addressed, mark as not_met.",
    },
    {
        "id": 7,
        "item": "Confirmed active homeowners insurance",
        "guidance": "Yes/no answer captured on whether they currently have "
                     "homeowners insurance.",
    },
    {
        "id": 8,
        "item": "Asked whether an insurance claim has already been filed, with "
                "the homeowner's answer captured",
        "guidance": "The agent asking the question is NOT enough on its own. The "
                     "homeowner must give an actual yes/no answer that is captured "
                     "in the transcript. If asked but not answered, mark as not_met.",
    },
    {
        "id": 9,
        "item": "Confirmed homeowner has not signed a contract with another "
                "roofing company",
        "guidance": "Explicit confirmation of no existing contract.",
    },
    {
        "id": 10,
        "item": "Scheduled a clear appointment date and time",
        "guidance": "A specific date AND time must be agreed upon — vague "
                     "commitments ('sometime next week') do not count.",
    },
    {
        "id": 11,
        "item": "Homeowner understands the appointment is for a roof inspection",
        "guidance": "Homeowner must acknowledge/confirm understanding, not just "
                     "have it stated at them without confirmation.",
    },
]

# All items are mandatory per business rule — every item must be "met" for
# the call to be QC_VALID. Items marked "met_but_disqualifying" (e.g. roof
# too new) should route to QC_NOT_VALID with a distinct reason.