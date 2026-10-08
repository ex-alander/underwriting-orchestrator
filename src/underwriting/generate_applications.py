"""Генератор синтетических кредитных заявок."""
import random
import uuid
from datetime import date, timedelta

from faker import Faker

from underwriting.schemas import (
    Application,
    CreditHistory,
    EmploymentType,
    LoanPurpose,
    Region
)


fake = Faker("ru_RU")


def _random_credit_history() -> CreditHistory:
    """Взвешенный выбор: 60% чистая история."""
    return random.choices(
        list(CreditHistory),
        weights=[60, 25, 10, 5],
    )[0]


def generate_application() -> Application:
    """Сгенерировать одну заявку."""
    employment = random.choices(
        list(EmploymentType),
        weights=[70, 15, 5, 10],
    )[0]

    # Доход зависит от занятости
    if employment == EmploymentType.EMPLOYED:
        income = random.uniform(60_000, 250_000)
    elif employment == EmploymentType.SELF_EMPLOYED:
        income = random.uniform(80_000, 400_000)
    elif employment == EmploymentType.RETIRED:
        income = random.uniform(25_000, 60_000)
    else:
        income = random.uniform(10_000, 40_000)

    region = random.choices(
        list(Region),
        weights=[30,15,10,10,9,7.5,7.5,5,5,1]
    )[0]
    
    # Долг — от 0% до 60% от дохода
    monthly_debt = income * random.uniform(0.0, 0.6)

    # Сумма кредита — 3–24 месячных дохода
    loan_amount = income * random.uniform(3, 24)

    return Application(
        application_id=str(uuid.uuid4()),
        full_name=f"{fake.last_name()} {fake.first_name()} {fake.middle_name()}",
        age=random.randint(21, 70),
        region=region,
        monthly_income=round(income, 2),
        monthly_debt=round(monthly_debt, 2),
        loan_amount=round(loan_amount, 2),
        loan_term_months=random.choice([12, 24, 36, 48, 60]),
        loan_purpose=random.choice(list(LoanPurpose)),
        employment_type=employment,
        credit_history=_random_credit_history(),
        applied_at=date.today() - timedelta(days=random.randint(0, 90)),
    )


def generate_batch(n: int = 30) -> list[Application]:
    """Сгенерировать n заявок."""
    return [generate_application() for _ in range(n)]
