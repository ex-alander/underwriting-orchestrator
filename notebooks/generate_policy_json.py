import json
from pathlib import Path
from collections import Counter

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# ИСТОЧНИКИ
# ---------------------------------------------------------------------------
# Политика упакована как «политика Альфа-Банка» по потребительскому
# кредитованию. Конкретные пункты восстановлены по открытым публикациям.
# В реальной работе каждое правило согласовывалось бы с юристами и бизнесом.

ALFA   = "https://alfabank.ru/get-money/credit/"
CBR    = "https://www.cbr.ru/analytics/"
BANKI  = "https://www.banki.ru/products/credits/"
FRANK  = "https://frankrg.com/"
RAEX   = "https://raexpert.ru/"

# ---------------------------------------------------------------------------
# ПРАВИЛА
# ---------------------------------------------------------------------------
# Логика такая: если condition == True, то срабатывает action.
# То есть условие описывает «плохую» ситуацию.
# Для мягких правил action="review", для жёстких — "reject".

policy = [
    # ========== INCOME ========== (12)
    {
        "id": "INCOME_MIN_15000",
        "category": "income",
        "description": "Минимальный месячный доход заёмщика — 15 000 руб.",
        "condition": {"metric": "monthly_income", "operator": "<", "value": 15000},
        "action": "reject",
        "reason": "Доход ниже минимально допустимого",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "INCOME_SOFT_25000",
        "category": "income",
        "description": "Доход ниже 25 000 руб. — заявку отправляем на ручную проверку.",
        "condition": {"metric": "monthly_income", "operator": "<", "value": 25000},
        "action": "review",
        "reason": "Низкий доход: требуется ручное рассмотрение",
        "severity": "medium",
        "source": BANKI,
    },
    {
        "id": "DTI_MAX_50",
        "category": "income",
        "description": "DTI (долговая нагрузка) не должен превышать 50%.",
        "condition": {"metric": "dti", "operator": ">", "value": 0.50},
        "action": "reject",
        "reason": "Предельная долговая нагрузка (DTI > 50%)",
        "severity": "high",
        "source": CBR,
    },
    {
        "id": "DTI_SOFT_40",
        "category": "income",
        "description": "DTI от 40% до 50% — заявку отправляем на ручную проверку.",
        "condition": {"metric": "dti", "operator": ">", "value": 0.40},
        "action": "review",
        "reason": "Повышенная долговая нагрузка (DTI > 40%)",
        "severity": "medium",
        "source": CBR,
    },
    {
        "id": "PTI_MAX_40",
        "category": "income",
        "description": "PTI (доля платежа по новому кредиту в доходе) не должен превышать 40%.",
        "condition": {"metric": "pti", "operator": ">", "value": 0.40},
        "action": "reject",
        "reason": "Платёж по кредиту превышает 40% дохода",
        "severity": "high",
        "source": BANKI,
    },
    {
        "id": "PTI_SOFT_30",
        "category": "income",
        "description": "PTI от 30% до 40% — заявку отправляем на ручную проверку.",
        "condition": {"metric": "pti", "operator": ">", "value": 0.30},
        "action": "review",
        "reason": "Повышенная доля платежа в доходе (PTI > 30%)",
        "severity": "medium",
        "source": BANKI,
    },
    {
        "id": "LOAN_AMOUNT_MAX_5M",
        "category": "income",
        "description": "Максимальная сумма потребительского кредита — 5 000 000 руб.",
        "condition": {"metric": "loan_amount", "operator": ">", "value": 5_000_000},
        "action": "reject",
        "reason": "Запрошенная сумма превышает лимит продукта",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "LOAN_AMOUNT_SOFT_3M",
        "category": "income",
        "description": "Сумма от 3 до 5 млн — заявку отправляем на ручную проверку.",
        "condition": {"metric": "loan_amount", "operator": ">", "value": 3_000_000},
        "action": "review",
        "reason": "Крупная сумма: требуется ручное рассмотрение",
        "severity": "medium",
        "source": ALFA,
    },
    {
        "id": "LOAN_TO_INCOME_MAX_30",
        "category": "income",
        "description": "Сумма кредита не должна превышать 30 месячных доходов.",
        "condition": {"metric": "loan_to_income_ratio", "operator": ">", "value": 30},
        "action": "reject",
        "reason": "Запрошенная сумма несоразмерна доходу",
        "severity": "high",
        "source": FRANK,
    },
    {
        "id": "LOAN_TO_INCOME_SOFT_20",
        "category": "income",
        "description": "Сумма кредита больше 20 месячных доходов — отправляем на ручную проверку.",
        "condition": {"metric": "loan_to_income_ratio", "operator": ">", "value": 20},
        "action": "review",
        "reason": "Крупная сумма относительно дохода",
        "severity": "medium",
        "source": FRANK,
    },
    {
        "id": "RATE_MIN_5",
        "category": "income",
        "description": "Ставка ниже 5% годовых не выдаётся (ниже ключевой ставки ЦБ).",
        "condition": {"metric": "interest_rate", "operator": "<", "value": 5.0},
        "action": "reject",
        "reason": "Ставка ниже минимально допустимой",
        "severity": "high",
        "source": CBR,
    },
    {
        "id": "RATE_MAX_40",
        "category": "income",
        "description": "Максимальная ставка по продукту — 40% годовых.",
        "condition": {"metric": "interest_rate", "operator": ">", "value": 40.0},
        "action": "reject",
        "reason": "Ставка превышает лимит продукта",
        "severity": "high",
        "source": ALFA,
    },

    # ========== PROFILE ========== (10)
    {
        "id": "CITIZENSHIP_RF",
        "category": "profile",
        "description": "Гражданство заёмщика — Российская Федерация.",
        "condition": {"metric": "citizenship", "operator": "not_in", "value": ["RF"]},
        "action": "reject",
        "reason": "Гражданство не соответствует требованиям продукта",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "AGE_MIN_21",
        "category": "profile",
        "description": "Минимальный возраст заёмщика — 21 год.",
        "condition": {"metric": "age", "operator": "<", "value": 21},
        "action": "reject",
        "reason": "Возраст меньше минимально допустимого",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "AGE_MAX_65",
        "category": "profile",
        "description": "Максимальный возраст заёмщика — 65 лет.",
        "condition": {"metric": "age", "operator": ">", "value": 65},
        "action": "reject",
        "reason": "Возраст превышает максимально допустимый",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "AGE_PLUS_TERM_70",
        "category": "profile",
        "description": "Возраст на момент погашения кредита не должен превышать 70 лет.",
        "condition": {"metric": "age_at_maturity", "operator": ">", "value": 70},
        "action": "reject",
        "reason": "Возраст на дату погашения превышает 70 лет",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "EMPLOYMENT_TYPE_VALID",
        "category": "profile",
        "description": "Тип занятости — наёмный сотрудник или ИП.",
        "condition": {
            "metric": "employment_type",
            "operator": "not_in",
            "value": ["salaried", "self_employed"],
        },
        "action": "reject",
        "reason": "Тип занятости не соответствует требованиям продукта",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "EMPLOYMENT_YEARS_MIN_0_5",
        "category": "profile",
        "description": "Минимальный стаж на текущем месте — 6 месяцев.",
        "condition": {"metric": "employment_years", "operator": "<", "value": 0.5},
        "action": "reject",
        "reason": "Стаж на текущем месте меньше 6 месяцев",
        "severity": "high",
        "source": BANKI,
    },
    {
        "id": "EMPLOYMENT_YEARS_SOFT_1",
        "category": "profile",
        "description": "Стаж меньше 1 года — отправляем на ручную проверку.",
        "condition": {"metric": "employment_years", "operator": "<", "value": 1.0},
        "action": "review",
        "reason": "Малый стаж на текущем месте",
        "severity": "medium",
        "source": BANKI,
    },
    {
        "id": "REGION_RF",
        "category": "profile",
        "description": "Заёмщик должен проживать на территории РФ.",
        "condition": {"metric": "region_in_rf", "operator": "==", "value": False},
        "action": "reject",
        "reason": "Регион проживания вне зоны обслуживания",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "NO_BANKRUPTCY",
        "category": "profile",
        "description": "Активная процедура банкротства — стоп-фактор.",
        "condition": {"metric": "has_bankruptcy", "operator": "==", "value": True},
        "action": "reject",
        "reason": "Наличие процедуры банкротства",
        "severity": "high",
        "source": CBR,
    },
    {
        "id": "RESIDENCE_PERMANENT_REVIEW",
        "category": "profile",
        "description": "Временная регистрация — отправляем на ручную проверку.",
        "condition": {"metric": "residence_type", "operator": "not_in", "value": ["permanent"]},
        "action": "review",
        "reason": "Временная регистрация",
        "severity": "medium",
        "source": BANKI,
    },

    # ========== CREDIT HISTORY ========== (12)
    {
        "id": "NO_DELINQUENCY_12M",
        "category": "credit_history",
        "description": "Нет просрочек за последние 12 месяцев.",
        "condition": {"metric": "had_delinquency_12m", "operator": "==", "value": True},
        "action": "reject",
        "reason": "Просрочки за последние 12 месяцев",
        "severity": "high",
        "source": CBR,
    },
    {
        "id": "NO_DELINQUENCY_24M_REVIEW",
        "category": "credit_history",
        "description": "Просрочки от 12 до 24 месяцев назад — отправляем на ручную проверку.",
        "condition": {"metric": "had_delinquency_24m", "operator": "==", "value": True},
        "action": "review",
        "reason": "Просрочки в истории 12–24 месяца назад",
        "severity": "medium",
        "source": CBR,
    },
    {
        "id": "NO_CURRENT_OVERDUE",
        "category": "credit_history",
        "description": "Нет текущей просроченной задолженности.",
        "condition": {"metric": "has_current_overdue", "operator": "==", "value": True},
        "action": "reject",
        "reason": "Текущая просроченная задолженность",
        "severity": "high",
        "source": CBR,
    },
    {
        "id": "ACTIVE_CREDITS_MAX_5",
        "category": "credit_history",
        "description": "Не более 5 активных кредитов одновременно.",
        "condition": {"metric": "active_credits_count", "operator": ">", "value": 5},
        "action": "reject",
        "reason": "Слишком много активных кредитов",
        "severity": "high",
        "source": BANKI,
    },
    {
        "id": "ACTIVE_CREDITS_SOFT_3",
        "category": "credit_history",
        "description": "Больше 3 активных кредитов — отправляем на ручную проверку.",
        "condition": {"metric": "active_credits_count", "operator": ">", "value": 3},
        "action": "review",
        "reason": "Много активных кредитов",
        "severity": "medium",
        "source": BANKI,
    },
    {
        "id": "CREDIT_HISTORY_YEARS_MIN_1",
        "category": "credit_history",
        "description": "Минимальная длина кредитной истории — 1 год.",
        "condition": {"metric": "credit_history_years", "operator": "<", "value": 1},
        "action": "reject",
        "reason": "Кредитная история короче года",
        "severity": "high",
        "source": FRANK,
    },
    {
        "id": "CREDIT_HISTORY_YEARS_SOFT_2",
        "category": "credit_history",
        "description": "Кредитная история меньше 2 лет — отправляем на ручную проверку.",
        "condition": {"metric": "credit_history_years", "operator": "<", "value": 2},
        "action": "review",
        "reason": "Короткая кредитная история",
        "severity": "medium",
        "source": FRANK,
    },
    {
        "id": "NO_WRITEOFFS",
        "category": "credit_history",
        "description": "Нет списанных безнадёжных долгов.",
        "condition": {"metric": "has_writeoffs", "operator": "==", "value": True},
        "action": "reject",
        "reason": "Списанные безнадёжные долги в истории",
        "severity": "high",
        "source": CBR,
    },
    {
        "id": "NO_COLLECTIONS",
        "category": "credit_history",
        "description": "Нет передач долга коллекторам.",
        "condition": {"metric": "has_collections", "operator": "==", "value": True},
        "action": "reject",
        "reason": "Передачи долга коллекторам в истории",
        "severity": "high",
        "source": CBR,
    },
    {
        "id": "INQUIRIES_12M_MAX_10",
        "category": "credit_history",
        "description": "Не более 10 запросов кредитной истории за последние 12 месяцев.",
        "condition": {"metric": "inquiries_12m", "operator": ">", "value": 10},
        "action": "reject",
        "reason": "Слишком много запросов кредитной истории за год",
        "severity": "high",
        "source": FRANK,
    },
    {
        "id": "INQUIRIES_12M_SOFT_5",
        "category": "credit_history",
        "description": "Больше 5 запросов за 12 месяцев — отправляем на ручную проверку.",
        "condition": {"metric": "inquiries_12m", "operator": ">", "value": 5},
        "action": "review",
        "reason": "Повышенная активность запросов КИ",
        "severity": "medium",
        "source": FRANK,
    },
    {
        "id": "NO_RECENT_MISSED_6M",
        "category": "credit_history",
        "description": "Нет пропущенных платежей за последние 6 месяцев.",
        "condition": {"metric": "had_missed_payment_6m", "operator": "==", "value": True},
        "action": "reject",
        "reason": "Пропущенные платежи за последние 6 месяцев",
        "severity": "high",
        "source": CBR,
    },

    # ========== SPECIAL ========== (16)
    {
        "id": "INSURANCE_INFO_LARGE_LOAN",
        "category": "special",
        "description": "Для суммы больше 500 000 руб. клиенту предложить страхование жизни.",
        "condition": {"metric": "loan_amount", "operator": ">", "value": 500_000},
        "action": "info",
        "reason": "Рекомендуется страхование жизни для крупных сумм",
        "severity": "low",
        "source": ALFA,
    },
    {
        "id": "CALL_VERIFICATION_LARGE",
        "category": "special",
        "description": "Для суммы больше 1 000 000 руб. требуется звонок-верификация.",
        "condition": {"metric": "loan_amount", "operator": ">", "value": 1_000_000},
        "action": "review",
        "reason": "Требуется звонок-верификация клиента",
        "severity": "medium",
        "source": ALFA,
    },
    {
        "id": "ADDITIONAL_DOCS_500K",
        "category": "special",
        "description": "Для суммы больше 500 000 руб. запросить подтверждение дохода.",
        "condition": {"metric": "loan_amount", "operator": ">", "value": 500_000},
        "action": "review",
        "reason": "Требуется подтверждение дохода документами",
        "severity": "medium",
        "source": ALFA,
    },
    {
        "id": "COBORROWER_FOR_2M",
        "category": "special",
        "description": "Для суммы больше 2 000 000 руб. нужен созаёмщик или залог.",
        "condition": {"metric": "loan_amount", "operator": ">", "value": 2_000_000},
        "action": "review",
        "reason": "Требуется созаёмщик или залог",
        "severity": "medium",
        "source": BANKI,
    },
    {
        "id": "SALARY_CLIENT_BONUS",
        "category": "special",
        "description": "Зарплатному клиенту — скидка к ставке.",
        "condition": {"metric": "is_salary_client", "operator": "==", "value": True},
        "action": "info",
        "reason": "Зарплатный клиент: применяется скидка к ставке",
        "severity": "low",
        "source": ALFA,
    },
    {
        "id": "REPEAT_CLIENT_BONUS",
        "category": "special",
        "description": "Клиент с хорошей кредитной историей в банке — скидка к ставке.",
        "condition": {"metric": "is_good_repeat_client", "operator": "==", "value": True},
        "action": "info",
        "reason": "Повторный клиент с положительной историей",
        "severity": "low",
        "source": ALFA,
    },
    {
        "id": "LOAN_TERM_MIN_6",
        "category": "special",
        "description": "Минимальный срок кредита — 6 месяцев.",
        "condition": {"metric": "loan_term_months", "operator": "<", "value": 6},
        "action": "reject",
        "reason": "Срок меньше минимального",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "LOAN_TERM_MAX_84",
        "category": "special",
        "description": "Максимальный срок кредита — 84 месяца.",
        "condition": {"metric": "loan_term_months", "operator": ">", "value": 84},
        "action": "reject",
        "reason": "Срок превышает максимальный",
        "severity": "high",
        "source": ALFA,
    },
    {
        "id": "LOAN_TERM_SOFT_60",
        "category": "special",
        "description": "Срок больше 60 месяцев — отправляем на ручную проверку.",
        "condition": {"metric": "loan_term_months", "operator": ">", "value": 60},
        "action": "review",
        "reason": "Длинный срок кредита",
        "severity": "medium",
        "source": ALFA,
    },
    {
        "id": "YOUNG_BORROWER_REVIEW",
        "category": "special",
        "description": "Заёмщик в возрасте 21–23 лет — отправляем на ручную проверку.",
        "condition": {"metric": "age", "operator": "<=", "value": 23},
        "action": "review",
        "reason": "Молодой заёмщик: ручная проверка",
        "severity": "medium",
        "source": BANKI,
    },
    {
        "id": "NEAR_RETIREMENT_REVIEW",
        "category": "special",
        "description": "Заёмщик в возрасте 60–65 лет — отправляем на ручную проверку.",
        "condition": {"metric": "age", "operator": ">=", "value": 60},
        "action": "review",
        "reason": "Предпенсионный возраст: ручная проверка",
        "severity": "medium",
        "source": BANKI,
    },
    {
        "id": "SELF_EMPLOYED_REVIEW",
        "category": "special",
        "description": "Самозанятый клиент — отправляем на ручную проверку.",
        "condition": {"metric": "employment_type", "operator": "==", "value": "self_employed"},
        "action": "review",
        "reason": "Самозанятый клиент: требуется дополнительная проверка",
        "severity": "medium",
        "source": ALFA,
    },
    {
        "id": "INCOME_PROOF_LARGE",
        "category": "special",
        "description": "Доход больше 100 000 руб. в месяц — требуется подтверждение дохода.",
        "condition": {"metric": "monthly_income", "operator": ">", "value": 100_000},
        "action": "review",
        "reason": "Требуется подтверждение заявленного дохода",
        "severity": "medium",
        "source": ALFA,
    },
    {
        "id": "NO_INSURANCE_INFO",
        "category": "special",
        "description": "Клиент отказался от страхования — информируем о повышении ставки.",
        "condition": {"metric": "has_insurance", "operator": "==", "value": False},
        "action": "info",
        "reason": "Отказ от страхования: ставка может быть выше",
        "severity": "low",
        "source": ALFA,
    },
    {
        "id": "MILITARY_AGE_INFO",
        "category": "special",
        "description": "Мужчина 18–27 лет — информируем о возможной военной службе.",
        "condition": {"metric": "military_service_risk", "operator": "==", "value": True},
        "action": "info",
        "reason": "Потенциальный риск призыва на военную службу",
        "severity": "low",
        "source": RAEX,
    },
    {
        "id": "NO_ACTIVE_COLLECTION_ACCOUNT",
        "category": "special",
        "description": "Активный счёт в коллекторском агентстве — стоп-фактор.",
        "condition": {"metric": "has_active_collection_account", "operator": "==", "value": True},
        "action": "reject",
        "reason": "Активная передача долга коллекторам",
        "severity": "high",
        "source": CBR,
    },
]

# ---------------------------------------------------------------------------
# ПРОВЕРКА: 50 правил, баланс по категориям, уникальные id
# ---------------------------------------------------------------------------
assert len(policy) == 50, f"Ожидалось 50 правил, получено {len(policy)}"
ids = [r["id"] for r in policy]
assert len(ids) == len(set(ids)), "Найдены неуникальные id"
print("Всего правил:", len(policy))
print("По категориям:", dict(Counter(r["category"] for r in policy)))

# ---------------------------------------------------------------------------
# СОХРАНЕНИЕ
# ---------------------------------------------------------------------------
policy_path = DATA_DIR / "policy.json"
policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
print("Сохранено:", policy_path.resolve())

sources_md = DATA_DIR / "policy_sources.md"
sources_md.write_text(
    "# Источники кредитной политики\n\n"
    "Политика упакована как политика Альфа-Банка по потребительскому кредитованию.\n"
    "Все правила восстановлены по открытым публикациям.\n\n"
    "## Основные источники\n\n"
    f"- Официальный сайт Альфа-Банка: {ALFA}\n"
    f"- Аналитика ЦБ РФ: {CBR}\n"
    f"- Разбор кредитных продуктов на banki.ru: {BANKI}\n"
    f"- Отчёты Frank RG: {FRANK}\n"
    f"- Рейтинговое агентство RAEX: {RAEX}\n\n"
    "## Логика группировки правил\n\n"
    "- **income** — доход, долговая нагрузка (DTI, PTI), сумма и ставка;\n"
    "- **profile** — возраст, гражданство, занятость, регион;\n"
    "- **credit_history** — просрочки, активные кредиты, длина КИ;\n"
    "- **special** — процессные правила (страхование, верификация, бонусы).\n\n"
    "## Оговорка\n\n"
    "Это MVP-политика для учебного проекта. Реальная политика банка\n"
    "существенно сложнее, содержит сотни правил, скоринговые модели и\n"
    "согласована юридически.\n",
    encoding="utf-8",
)
print("Сохранено:", sources_md.resolve())