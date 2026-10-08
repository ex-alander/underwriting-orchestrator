from pathlib import Path
import json

def check_rule(rule: dict, metrics: dict) -> bool:
    """
    Проверяет одно правило политики против метрик заявки.
    Возвращает True, если условие правила выполнено.
    """
    cond = rule["condition"]
    metric = cond["metric"]
    op = cond["operator"]
    value = cond["value"]

    if metric not in metrics:
        raise ValueError(f"Метрика '{metric}' отсутствует в заявке")

    actual = metrics[metric]

    if op == ">":
        return actual > value
    if op == ">=":
        return actual >= value
    if op == "<":
        return actual < value
    if op == "<=":
        return actual <= value
    if op == "==":
        return actual == value
    if op == "in":
        return actual in value
    if op == "not_in":
        return actual not in value

    raise ValueError(f"Неизвестный оператор: {op}")

def validate_policy(policy, verbose=True):
    """
    Проверяет политику на корректность. Возвращает (ok, errors).
    ok     : True, если ошибок нет
    errors : список сообщений об ошибках
    """
    required_rule_fields = {"id", "category", "description",
                            "condition", "action", "reason",
                            "severity", "source"}
    required_condition_fields = {"metric", "operator", "value"}

    valid_operators = {">", ">=", "<", "<=", "==", "in", "not_in"}
    valid_actions = {"approve", "reject", "review", "lower_amount", "info"}
    valid_severities = {"high", "medium", "low"}
    valid_categories = {"income", "profile", "credit_history", "special"}

    errors = []
    seen_ids = set()

    if not isinstance(policy, list):
        return False, ["policy должен быть списком правил"]

    for i, rule in enumerate(policy):
        prefix = f"Правило #{i}"

        # 0. Вообще словарь ли это
        if not isinstance(rule, dict):
            errors.append(f"{prefix}: не словарь, а {type(rule).__name__}")
            continue

        rid = rule.get("id", "<без id>")
        prefix = f"Правило '{rid}'"

        # 1. Обязательные поля правила
        missing = required_rule_fields - set(rule.keys())
        if missing:
            errors.append(f"{prefix}: не хватает полей {sorted(missing)}")
            continue  # дальше проверять нечего

        # 2. Уникальность id
        if rid in seen_ids:
            errors.append(f"{prefix}: дубликат id")
        seen_ids.add(rid)

        # 3. category
        if rule["category"] not in valid_categories:
            errors.append(
                f"{prefix}: неизвестная category '{rule['category']}'. "
                f"Допустимо: {sorted(valid_categories)}"
            )

        # 4. action
        if rule["action"] not in valid_actions:
            errors.append(
                f"{prefix}: неизвестная action '{rule['action']}'. "
                f"Допустимо: {sorted(valid_actions)}"
            )

        # 5. severity
        if rule["severity"] not in valid_severities:
            errors.append(
                f"{prefix}: неизвестная severity '{rule['severity']}'. "
                f"Допустимо: {sorted(valid_severities)}"
            )

        # 6. description и reason — непустые строки
        for f in ("description", "reason"):
            if not isinstance(rule[f], str) or not rule[f].strip():
                errors.append(f"{prefix}: поле '{f}' пустое или не строка")

        # 7. condition
        cond = rule["condition"]
        if not isinstance(cond, dict):
            errors.append(f"{prefix}: condition должен быть словарём")
            continue

        missing_cond = required_condition_fields - set(cond.keys())
        if missing_cond:
            errors.append(
                f"{prefix}: в condition не хватает полей {sorted(missing_cond)}"
            )
            continue

        if cond["operator"] not in valid_operators:
            errors.append(
                f"{prefix}: неизвестный operator '{cond['operator']}'. "
                f"Допустимо: {sorted(valid_operators)}"
            )

        if not isinstance(cond["metric"], str) or not cond["metric"].strip():
            errors.append(f"{prefix}: metric должен быть непустой строкой")

        # value: для in/not_in — список, для остальных — число или строка
        val = cond["value"]
        if cond["operator"] in ("in", "not_in"):
            if not isinstance(val, (list, tuple, set)):
                errors.append(
                    f"{prefix}: для operator '{cond['operator']}' "
                    f"value должен быть списком, а не {type(val).__name__}"
                )
        else:
            if not isinstance(val, (int, float, str, bool)):
                errors.append(
                    f"{prefix}: value должен быть числом или строкой, "
                    f"а не {type(val).__name__}"
                )

    ok = len(errors) == 0
    if verbose:
        if ok:
            print(f"✅ policy валидна: {len(policy)} правил, ошибок нет")
        else:
            print(f"❌ найдено ошибок: {len(errors)}")
            for e in errors:
                print("   -", e)
    return ok, errors

def load_policy(path: str | Path = "data/policy.json") -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)
