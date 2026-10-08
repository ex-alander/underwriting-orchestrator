"""Pydantic-схемы для кредитной заявки."""
from datetime import date
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class EmploymentType(str, Enum):
    EMPLOYED = "employed"
    SELF_EMPLOYED = "self_employed"
    UNEMPLOYED = "unemployed"
    RETIRED = "retired"


class LoanPurpose(str, Enum):
    CONSUMER = "consumer"
    AUTO = "auto"
    MORTGAGE = "mortgage"
    REFINANCE = "refinance"


class CreditHistory(str, Enum):
    CLEAN = "clean"
    MINOR_DELAYS = "minor_delays"
    SERIOUS_DELAYS = "serious_delays"
    NO_HISTORY = "no_history"

class Region(str, Enum):
    MOSCOW = "moscow"
    SAINT_PETERSBURG = "saint_petersburg"
    MOSCOW_OBLAST = "moscow_oblast"
    LENINGRAD_OBLAST = "leningrad_oblast"
    KRASNODAR_KRAI = "krasnodar_krai"
    SVERDLOVSK_OBLAST = "sverdlovsk_oblast"
    TATARSTAN = "tatarstan"
    NOVOSIBIRSK_OBLAST = "novosibirsk_oblast"
    ROSTOV_OBLAST = "rostov_oblast"
    PRIMORSKY_KRAI = "primorsky_krai"

class Category(str, Enum):
    INCOME = "income"
    PROFILE = "profile"
    CREDIT_HISTORY = "credit_history"
    SPECIAL = "special"

class Operator(str, Enum):
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    IN = "in"
    NOT_IN = "not_in"

class Condition(BaseModel):
    metric: str
    operator: Operator
    value: Any

class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class Action(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REVIEW = "review"
    LOWER_AMOUNT = "lower_amount"
    INFO = "info"

class Rule(BaseModel):
    id: str
    category: Category
    description: str
    condition: Condition
    action: Action
    reason: str
    severity: Severity
    source: str

class ParsedRule(BaseModel):
    source_url: str
    raw_text: str

class Application(BaseModel):
    """Одна кредитная заявка."""
    application_id: str
    full_name: str
    age: int = Field(ge=18, le=80)
    region: Region
    monthly_income: float = Field(gt=0)
    monthly_debt: float = Field(ge=0)
    loan_amount: float = Field(gt=0)
    loan_term_months: int = Field(ge=6, le=360)
    loan_purpose: LoanPurpose
    employment_type: EmploymentType
    credit_history: CreditHistory
    applied_at: date

# ============================================
# GOLD STANDARD
# ============================================
class ExpectedRuleResult(BaseModel):
    """Ожидаемый результат проверки одного правила для одной заявки."""
    rule_id: str
    passed: bool
    reason: str | None = None

class GoldApplication(BaseModel):
    """Эталон для одной заявки."""
    application_id: str
    expected_rules: list[ExpectedRuleResult]
    expected_verdict: str  # "approve" | "reject" | "review"
    expected_rate: float | None = None
    notes: str | None = None

# ============================================
# EVALUATION
# ============================================

class EvaluationReport(BaseModel):
    """Результат оценки одной партии заявок."""
    total: int
    correct: int
    precision: float
    recall: float
    f1: float
    accuracy: float
    per_field: dict[str, dict[str, float]] = {}