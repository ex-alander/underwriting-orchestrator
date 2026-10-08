"""Тесты оценки качества агентов."""
import pytest

from underwriting.evaluation import evaluate_field_extraction, evaluate_rule_results
from underwriting.schemas import ExpectedRuleResult


def test_evaluate_perfect_match():
    """Все правила совпали → precision=recall=f1=accuracy=1.0."""
    results = [
        ExpectedRuleResult(rule_id=f"R{i}", passed=True) for i in range(5)
    ]
    report = evaluate_rule_results(results, results)
    assert report.accuracy == 1.0
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.f1 == 1.0


def test_evaluate_all_wrong():
    """Все правила не совпали → метрики 0."""
    predicted = [ExpectedRuleResult(rule_id=f"R{i}", passed=True) for i in range(5)]
    expected = [ExpectedRuleResult(rule_id=f"R{i}", passed=False) for i in range(5)]
    report = evaluate_rule_results(predicted, expected)
    assert report.accuracy == 0.0
    assert report.precision == 0.0
    assert report.recall == 0.0


def test_evaluate_mixed():
    """3 из 4 угаданы → accuracy = 0.75."""
    predicted = [
        ExpectedRuleResult(rule_id="R1", passed=True),
        ExpectedRuleResult(rule_id="R2", passed=True),
        ExpectedRuleResult(rule_id="R3", passed=False),
        ExpectedRuleResult(rule_id="R4", passed=True),
    ]
    expected = [
        ExpectedRuleResult(rule_id="R1", passed=True),
        ExpectedRuleResult(rule_id="R2", passed=True),
        ExpectedRuleResult(rule_id="R3", passed=True),
        ExpectedRuleResult(rule_id="R4", passed=True),
    ]
    report = evaluate_rule_results(predicted, expected)
    assert report.accuracy == 0.75


def test_evaluate_size_mismatch():
    predicted = [ExpectedRuleResult(rule_id="R1", passed=True)]
    expected = [
        ExpectedRuleResult(rule_id="R1", passed=True),
        ExpectedRuleResult(rule_id="R2", passed=True),
    ]
    with pytest.raises(ValueError):
        evaluate_rule_results(predicted, expected)


def test_evaluate_field_extraction_perfect():
    predicted = {"age": 35, "income": 80_000, "region": "moscow"}
    expected = {"age": 35, "income": 80_000, "region": "moscow"}
    report = evaluate_field_extraction(predicted, expected, ["age", "income", "region"])
    assert report.accuracy == 1.0


def test_evaluate_field_extraction_partial():
    predicted = {"age": 35, "income": 90_000, "region": "moscow"}
    expected = {"age": 35, "income": 80_000, "region": "moscow"}
    report = evaluate_field_extraction(predicted, expected, ["age", "income", "region"])
    assert abs(report.accuracy - 0.6667) < 0.001
