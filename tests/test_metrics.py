"""Тесты метрик заявки."""
import pytest

from underwriting.metrics import full_dti, monthly_payment, pti


def test_monthly_payment_known_value():
    """500 000 под 18% на 36 месяцев ≈ 18 076 ₽."""
    payment = monthly_payment(500_000, 0.18, 36)
    assert abs(payment - 18_076) < 10


def test_monthly_payment_zero_rate():
    """При нулевой ставке платёж = сумма / срок."""
    assert monthly_payment(120_000, 0.0, 12) == 10_000


def test_monthly_payment_invalid_term():
    with pytest.raises(ValueError):
        monthly_payment(500_000, 0.18, 0)


def test_monthly_payment_invalid_amount():
    with pytest.raises(ValueError):
        monthly_payment(0, 0.18, 36)


def test_pti_normal():
    """Платёж 18 076 при доходе 80 000 → PTI ≈ 0.226."""
    assert abs(pti(18_076, 80_000) - 0.226) < 0.001


def test_pti_invalid_income():
    with pytest.raises(ValueError):
        pti(18_076, 0)


def test_full_dti_normal():
    """Платёж 18 076, долг 5 000, доход 80 000 → DTI ≈ 0.288."""
    assert abs(full_dti(18_076, 5_000, 80_000) - 0.288) < 0.001


def test_full_dti_no_existing_debt():
    """Без существующих долгов DTI совпадает с PTI."""
    assert full_dti(18_076, 0, 80_000) == pti(18_076, 80_000)
