"""Прогон всех валидаторов: policy.json, applications.jsonl, gold_standard.json."""
import json
import sys
from pathlib import Path

from underwriting.policy import validate_policy
from underwriting.schemas import Application, GoldApplication


def validate_policy_file(path: Path) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, [f"Файл не найден: {path}"]
    with path.open(encoding="utf-8") as f:
        policy = json.load(f)
    return validate_policy(policy, verbose=False)


def validate_applications(path: Path) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, [f"Файл не найден: {path}"]

    errors: list[str] = []
    count = 0
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                Application.model_validate(json.loads(line))
                count += 1
            except Exception as e:
                errors.append(f"Строка {i}: {e}")

    if errors:
        return False, errors
    print(f"  ✓ applications.jsonl: {count} заявок валидны")
    return True, []


def validate_gold(path: Path) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, [f"Файл не найден: {path}"]

    with path.open(encoding="utf-8") as f:
        raw = json.load(f)

    if "applications" not in raw:
        return False, ["В gold_standard.json нет поля 'applications'"]

    errors: list[str] = []
    for i, item in enumerate(raw["applications"]):
        try:
            GoldApplication.model_validate(item)
        except Exception as e:
            errors.append(f"Заявка #{i}: {e}")

    if errors:
        return False, errors
    print(f"  ✓ gold_standard.json: {len(raw['applications'])} эталонов валидны")
    return True, []


def main() -> int:
    print("Валидация всех артефактов фазы 1...\n")
    all_ok = True

    checks = [
        ("policy.json", Path("data/policy.json"), validate_policy_file),
        ("applications.jsonl", Path("data/applications.jsonl"), validate_applications),
        ("gold_standard.json", Path("data/gold_standard.json"), validate_gold),
    ]

    for name, path, validator in checks:
        ok, errors = validator(path)
        if ok:
            print(f"✓ {name}")
        else:
            all_ok = False
            print(f"✗ {name}")
            for e in errors[:5]:
                print(f"    {e}")
            if len(errors) > 5:
                print(f"    ...и ещё {len(errors) - 5}")

    print()
    if all_ok:
        print("Все артефакты валидны.")
        return 0
    print("Есть ошибки, исправь перед продолжением.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
