from app.modules.eligibility.engine import Operator, Rule, evaluate

RULES = [
    Rule(field="cgpa", operator=Operator.GTE, value=7.0, label="Minimum CGPA 7.0"),
    Rule(field="active_backlogs", operator=Operator.LTE, value=0, label="No active backlogs"),
]


def test_same_rule_version_and_facts_are_deterministic() -> None:
    facts = {"cgpa": 8.2, "active_backlogs": 0}
    assert evaluate("northstar-v1", RULES, facts) == evaluate("northstar-v1", RULES, facts)
    assert evaluate("northstar-v1", RULES, facts)["status"] == "eligible"


def test_missing_data_requires_review_instead_of_rejection() -> None:
    result = evaluate("northstar-v1", RULES, {"cgpa": 8.2})
    assert result["status"] == "needs_manual_review"
