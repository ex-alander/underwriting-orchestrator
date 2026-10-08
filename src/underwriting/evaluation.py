"""Оценка качества агентов: precision, recall, F1, accuracy."""
from .schemas import EvaluationReport, ExpectedRuleResult


def evaluate_rule_results(
    predicted: list[ExpectedRuleResult],
    expected: list[ExpectedRuleResult],
) -> EvaluationReport:
    """Сравнить предсказанные результаты по правилам с эталоном.

    Считаем по каждому правилу: сработало или нет.
    True positive — правило должно было сработать и сработало.
    """
    if len(predicted) != len(expected):
        raise ValueError(
            f"Размеры не совпадают: predicted={len(predicted)}, expected={len(expected)}"
        )

    tp = fp = fn = tn = 0
    correct = 0

    for p, e in zip(predicted, expected):
        if p.rule_id != e.rule_id:
            raise ValueError(f"rule_id не совпадают: {p.rule_id} vs {e.rule_id}")

        if p.passed and e.passed:
            tp += 1
            correct += 1
        elif p.passed and not e.passed:
            fp += 1
        elif not p.passed and e.passed:
            fn += 1
        else:
            tn += 1
            correct += 1

    total = len(expected)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = correct / total if total > 0 else 0.0

    return EvaluationReport(
        total=total,
        correct=correct,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        accuracy=round(accuracy, 4),
    )


def evaluate_field_extraction(
    predicted: dict,
    expected: dict,
    fields: list[str],
) -> EvaluationReport:
    """Оценить качество извлечения полей из заявки.

    Для каждого поля: совпало ли предсказание с эталоном.
    Считаем по всем полям общий accuracy.
    """
    correct = 0
    total = 0
    per_field: dict[str, dict[str, float]] = {}

    for field in fields:
        expected_value = expected.get(field)
        predicted_value = predicted.get(field)
        match = predicted_value == expected_value
        total += 1
        if match:
            correct += 1
        per_field[field] = {"correct": float(match), "total": 1.0}

    accuracy = correct / total if total > 0 else 0.0

    return EvaluationReport(
        total=total,
        correct=correct,
        precision=accuracy,
        recall=accuracy,
        f1=accuracy,
        accuracy=round(accuracy, 4),
        per_field=per_field,
    )
