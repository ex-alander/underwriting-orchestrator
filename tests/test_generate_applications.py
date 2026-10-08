"""Тесты генератора заявок."""
from collections import Counter

from underwriting.generate_applications import generate_application, generate_batch
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

def test_region_field_present():
    """У каждой заявки есть регион из допустимого списка."""
    from underwriting.schemas import Region

    apps = generate_batch(50)
    allowed = set(Region)
    for app in apps:
        assert app.region in allowed


def test_regions_distribution():
    """Москва встречается чаще, чем Приморский край (веса соблюдены)."""
    apps = generate_batch(300)
    moscow_count = sum(1 for a in apps if a.region.value == "moscow")
    primorsky_count = sum(1 for a in apps if a.region.value == "primorsky")
    assert moscow_count > primorsky_count


def test_income_depends_on_employment():
    """Самозанятые в среднем зарабатывают больше безработных."""
    apps = generate_batch(200)
    self_employed = [a.monthly_income for a in apps if a.employment_type.value == "self_employed"]
    unemployed = [a.monthly_income for a in apps if a.employment_type.value == "unemployed"]
    if self_employed and unemployed:
        assert sum(self_employed) / len(self_employed) > sum(unemployed) / len(unemployed)
