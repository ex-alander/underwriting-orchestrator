"""Загрузка и работа с gold standard."""
import json
from pathlib import Path

from .schemas import GoldApplication


def load_gold_standard(
    path: str | Path = "data/gold_standard.json",
) -> dict[str, GoldApplication]:
    """Загрузить gold standard. Возвращает словарь {application_id: GoldApplication}."""
    with Path(path).open(encoding="utf-8") as f:
        raw = json.load(f)

    gold_list = [GoldApplication.model_validate(item) for item in raw["applications"]]
    return {g.application_id: g for g in gold_list}


def find_gold(
    application_id: str,
    path: str | Path = "data/gold_standard.json",
) -> GoldApplication | None:
    """Найти эталон для одной заявки по ID."""
    gold = load_gold_standard(path)
    return gold.get(application_id)
