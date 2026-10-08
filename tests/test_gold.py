"""Тесты загрузки gold standard."""
from underwriting.gold import find_gold, load_gold_standard


def test_load_gold_standard():
    gold = load_gold_standard()
    assert len(gold) >= 10


def test_gold_ids_unique():
    gold = load_gold_standard()
    assert len(gold) == len(set(gold.keys()))


def test_gold_has_required_fields():
    gold = load_gold_standard()
    for app_id, g in gold.items():
        assert g.application_id == app_id
        assert len(g.expected_rules) > 0
        assert g.expected_verdict in {"approve", "reject", "review"}


def test_find_gold_existing():
    gold = load_gold_standard()
    first_id = next(iter(gold))
    found = find_gold(first_id)
    assert found is not None
    assert found.application_id == first_id


def test_find_gold_missing():
    assert find_gold("this-id-does-not-exist") is None
