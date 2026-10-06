"""Тесты для credit_math."""
import pytest

from underwriting.credit_math import calc_dti, calc_payment, calc_loan_schedule

def test_calc_dti_normal():
    assert calc_dti(30_000, 100_000) == 0.3


def test_calc_dti_zero_debt():
    assert calc_dti(0, 100_000) == 0.0


def test_calc_dti_debt_exceeds_income():
    assert calc_dti(150_000, 100_000) == 1.5


def test_calc_dti_invalid_income():
    with pytest.raises(ValueError):
        calc_dti(30_000, 0)


def test_calc_payment_normal():
    payment = calc_payment(1_000_000, 0.15, 60)
    assert abs(payment - 23_790) < 10


def test_calc_payment_invalid_months():
    with pytest.raises(ValueError):
        calc_payment(1_000_000, 0.15, 0)

def test_calc_loan_schedule_principal_sum():
    schedule = calc_loan_schedule(1_000_000, 0.15, 60)
    principal_sum = sum([s['principal'] for s in schedule])
    assert abs(principal_sum-1_000_000)<10

def test_calc_loan_schedule_first_interest():
    schedule = calc_loan_schedule(1_000_000, 0.15, 60)
    assert abs(schedule[0]['interest'] - 1_000_000*0.15/12) < 10