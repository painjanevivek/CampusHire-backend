"""Colleges displayed in the public student signup form."""

SIGNUP_COLLEGES = (
    ("pccoe-pune", "Pimpri Chinchwad College of Engineering (PCCOE), Pune."),
    ("pccoer-pune", "Pimpri Chinchwad College of Engineering & Research (PCCOE&R), Pune."),
    ("nmiet-pune", "Nutan Maharashtra Institute of Engineering & Technology (NMIET), Pune."),
    ("ncer-pune", "Nutan College of Engineering & Research (NCER), Pune."),
    ("pcu-pune", "Pimpri Chinchwad University (PCU), Pune."),
)

SIGNUP_COLLEGE_CODES = tuple(code for code, _ in SIGNUP_COLLEGES)

# The public catalog can advertise upcoming institutions while self-service
# student registration remains explicitly enabled for PCCOE only.
SIGNUP_ENABLED_COLLEGE_CODES = ("pccoe-pune",)
