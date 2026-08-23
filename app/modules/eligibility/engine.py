from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Operator(StrEnum):
    EQ = "eq"
    IN = "in"
    GTE = "gte"
    LTE = "lte"
    PRESENT = "present"


class Rule(BaseModel):
    field: str = Field(
        pattern=r"^(department|degree|branch|graduation_year|cgpa|active_backlogs|github|portfolio|resume)$"
    )
    operator: Operator
    value: Any = None
    label: str = Field(min_length=2, max_length=200)

    @model_validator(mode="after")
    def validate_operator_value(self) -> "Rule":
        if self.operator is Operator.PRESENT:
            return self
        if self.operator is Operator.IN and (
            not isinstance(self.value, list) or not self.value
        ):
            raise ValueError("The in operator requires a non-empty list")
        if self.operator in {Operator.GTE, Operator.LTE} and (
            isinstance(self.value, bool) or not isinstance(self.value, (int, float))
        ):
            raise ValueError("Comparison rules require a numeric value")
        if self.operator is Operator.EQ and self.value is None:
            raise ValueError("Equality rules require a value")
        return self


class RuleResult(BaseModel):
    field: str
    operator: Operator
    label: str
    passed: bool | None
    reason: str
    actual: Any = None
    expected: Any = None


def evaluate_rule(rule: Rule, facts: dict[str, Any]) -> RuleResult:
    if rule.field not in facts or facts[rule.field] is None:
        return RuleResult(
            field=rule.field,
            operator=rule.operator,
            label=rule.label,
            passed=None,
            reason="Required profile data is missing",
            actual=None,
            expected=rule.value,
        )
    actual = facts[rule.field]
    if rule.operator is Operator.EQ:
        passed = actual == rule.value
    elif rule.operator is Operator.IN:
        passed = actual in rule.value
    elif rule.operator is Operator.GTE:
        passed = actual >= rule.value
    elif rule.operator is Operator.LTE:
        passed = actual <= rule.value
    else:
        passed = bool(actual)
    return RuleResult(
        field=rule.field,
        operator=rule.operator,
        label=rule.label,
        passed=passed,
        reason="Requirement met" if passed else f"Profile value {actual!s} does not meet this rule",
        actual=actual,
        expected=rule.value,
    )


def evaluate(rule_version: str, rules: list[Rule], facts: dict[str, Any]) -> dict[str, Any]:
    results = [evaluate_rule(rule, facts) for rule in rules]
    status = (
        "needs_manual_review"
        if any(item.passed is None for item in results)
        else "eligible"
        if all(item.passed for item in results)
        else "ineligible"
    )
    return {
        "status": status,
        "rule_version": rule_version,
        "results": [item.model_dump() for item in results],
    }
