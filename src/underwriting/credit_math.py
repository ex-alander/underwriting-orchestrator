"""Кредитные формулы: DTI, аннуитетный платёж."""


def calc_dti(monthly_debt: float, monthly_income: float) -> float:
    """Возвращает debt-to-income ratio."""
    if monthly_income <= 0:
        raise ValueError("monthly_income must be positive")
    return monthly_debt / monthly_income


def calc_payment(principal: float, annual_rate: float, months: int) -> float:
    """Ежемесячный аннуитетный платёж."""
    if months <= 0:
        raise ValueError("months must be positive")
    if principal <= 0:
        raise ValueError("principal must be positive")
    monthly_rate = annual_rate / 12
    return principal * monthly_rate / (1 - (1 + monthly_rate) ** (-months))

def calc_loan_schedule(principal, rate, months):
    if months <= 0:
        raise ValueError("months must be positive")
    if principal <= 0:
        raise ValueError("principal must be positive")

    monthly_rate = rate / 12
    payment = calc_payment(principal, rate, months)
    balance = principal
    schedule = []

    for month in range(1, months + 1):
        interest = balance * monthly_rate
        debt = payment - interest
        balance = balance - debt
        schedule.append({
            "month": month,
            "payment": payment,
            "interest": interest,
            "principal": debt,
            "balance": balance,
        })

    return schedule