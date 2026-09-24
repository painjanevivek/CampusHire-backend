"""Colleges currently offered in the public student signup flow."""

SIGNUP_COLLEGES = (
    ("pccoe-pune", "Pimpri Chinchwad College of Engineering (PCCOE), Pune."),
)

SIGNUP_COLLEGE_CODES = tuple(code for code, _ in SIGNUP_COLLEGES)
