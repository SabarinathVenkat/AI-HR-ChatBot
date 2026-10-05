"""Retrieval question sets.

DEV is used to tune the abstain threshold. HELD_OUT was written before any retrieval results were
seen and is run once at the end; do not tune against it.

Each answerable item is (question, acceptable section ids). A hit in the top 3 on any acceptable
section counts as found.
"""

DEV_ANSWERABLE = [
    ("How long is the notice period after confirmation?", {"POL-05 §3"}),
    ("How many annual leave days do I get per year?", {"POL-02 §2"}),
    ("Can I carry forward unused leave?", {"POL-02 §7"}),
    ("What is the maximum number of days of annual leave I can take at once?", {"POL-02 §4"}),
    ("How many days of paternity leave do I get?", {"POL-02 §2", "POL-02 §6"}),
    ("When is salary credited each month?", {"POL-06 §1"}),
    ("What is the probation period?", {"POL-05 §1"}),
    ("How many days a week do I work from the office?", {"POL-04 §1"}),
    ("What is the learning budget?", {"POL-07 §5"}),
    ("Who do I contact for sexual harassment complaints?", {"POL-08 §2"}),
    ("Which days are public holidays in October?", {"POL-03 §1"}),
    ("What is the hotel limit for travel?", {"POL-07 §2"}),
    ("How is leave counted when a holiday falls in between?", {"POL-02 §5"}),
    ("What happens to my leave encashment when I resign?", {"POL-02 §7", "POL-05 §5"}),
    ("What is the employee referral bonus?", {"POL-01 §6"}),
    ("How does the appraisal cycle work?", {"POL-06 §3"}),
    ("Is a medical certificate needed for sick leave?", {"POL-02 §4"}),
    ("What is the group medical insurance cover?", {"POL-06 §4"}),
    ("What are the company's values?", {"POL-01 §2"}),
    ("How does the hiring process work?", {"POL-01 §4"}),
]

DEV_UNANSWERABLE = [
    "What is the dress code?",
    "What is on the cafeteria menu today?",
    "How do I book a meeting room?",
    "What is the CEO's salary?",
    "What stock options do employees get?",
    "Is there a gym membership benefit?",
    "What's the weather in Chennai today?",
    "How do I reset my laptop password?",
    "Can I bring my pet to the office?",
    "What is the parking policy?",
]

HELD_OUT_ANSWERABLE = [
    ("What is the notice period for managers?", {"POL-05 §3"}),
    ("How many sick leave days do I get in a year?", {"POL-02 §2"}),
    ("What happens if I take leave beyond my balance?", {"POL-02 §4", "POL-02 §8"}),
    ("Can I work from home?", {"POL-04 §1", "POL-04 §2"}),
    ("How do I claim a certification fee?", {"POL-07 §5"}),
    ("What is the home office allowance?", {"POL-07 §4"}),
    ("How long does full and final settlement take?", {"POL-05 §5"}),
    ("Who handles complaints about harassment?", {"POL-08 §2"}),
    ("What is the gift limit from clients?", {"POL-08 §1"}),
    ("How is loss of pay calculated?", {"POL-02 §8"}),
]

HELD_OUT_UNANSWERABLE = [
    "What is the company's mission statement for 2030?",
    "How do I apply for a visa?",
    "Which health club can I join?",
    "Who won the cricket match?",
    "What is the salary of a senior engineer?",
    "How do I order food at the office?",
]
