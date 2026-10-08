"""Метрики заявки: аннуитетный платёж, PTI, DTI.

В фазе 2 эти метрики вычисляются перед проверкой правил,
потому что часть правил смотрит на производные величины,
а не на сырые поля заявки.
"""
from .schemas import Application


def monthly_payment(
    loan_amount: float,
    annual_rate: float,
    term_months: int,
) -> float:
    """Ежемесячный аннуитетный платёж.

    annual_rate — доля, а не проценты (0.18 вместо 18).
    """
    if term_months <= 0:
        raise ValueError("term_months must be positive")
    if loan_amount <= 0:
        raise ValueError("loan_amount must be positive")

    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        return loan_amount / term_months

    factor = (1 + monthly_rate) ** term_months
    return loan_amount * monthly_rate * factor / (factor - 1)


def pti(payment: float, monthly_income: float) -> float:
    """Payment-to-Income: доля дохода, уходящая на новый кредит."""
    if monthly_income <= 0:
        raise ValueError("monthly_income must be positive")
    return payment / monthly_income


def full_dti(
    payment: float,
    existing_debt: float,
    monthly_income: float,
) -> float:
    """Debt-to-Income с учётом нового платежа и существующих долгов."""
    if monthly_income <= 0:
        raise ValueError("monthly_income must be positive")
    return (payment + existing_debt) / monthly_income


def compute_application_metrics(
    application: Application,
    annual_rate: float = 0.18,
) -> dict[str, float | int | str | bool]:
    """Собрать все метрики заявки в один словарь.

    annual_rate — предполагаемая ставка, по которой считается новый платёж.
    Пока используем 18% как заглушку, в фазе 2 ставка будет вычисляться
    через pricing-агент.
    """
    payment = monthly_payment(
        application.loan_amount, annual_rate, application.loan_term_months
    )
    return {
        "application_id": application.application_id,
        "age": application.age,
        "monthly_income": application.monthly_income,
        "monthly_debt": application.monthly_debt,
        "loan_amount": application.loan_amount,
        "loan_term_months": application.loan_term_months,
        "loan_purpose": application.loan_purpose.value,
        "employment_type": application.employment_type.value,
        "credit_history": application.credit_history.value,
        "region": application.region.value,
        "monthly_payment": round(payment, 2),
        "pti": round(pti(payment, application.monthly_income), 4),
        "dti": round(
            full_dti(payment, application.monthly_debt, application.monthly_income),
            4,
        ),
    }
