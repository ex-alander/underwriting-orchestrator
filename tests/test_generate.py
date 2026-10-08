"""Тесты генератора заявок."""
from collections import Counter

from underwriting.generate import generate_application, generate_batch
from underwriting.schemas import Application, Region


def test_generate_one_application():
    app = generate_application()
    assert isinstance(app, Application)
    assert 18 <= app.age <= 80
    assert app.monthly_income > 0
    assert app.loan_term_months >= 6


def test_generate_batch_size():
    apps = generate_batch(30)
    assert len(apps) == 30
    assert all(isinstance(a, Application) for a in apps)


def test_ids_are_unique():
    apps = generate_batch(30)
    ids = [a.application_id for a in apps]
    assert len(ids) == len(set(ids))


def test_distribution_is_realistic():
    """Не более 15% безработных — мы задавали вес 5%."""
    apps = generate_batch(200)
    unemployed = sum(1 for a in apps if a.employment_type.value == "unemployed")
    assert unemployed / len(apps) < 0.15

def test_regions_are_from_enum():
    apps = generate_batch(50)
    for app in apps:
        assert app.region in list(Region)