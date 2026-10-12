"""
CLI для полного пайплайна кредитного андеррайтинга. Версия 3.

Что нового по сравнению с v2:
1. Policy check: все числовые сравнения вынесены в Python (check_rule).
   LLM вызывается только для семантических правил.
2. Verdict: Python сам обходит ВСЕ правила из policy.json, а не только те,
   что вернула LLM. Пропущенные правила автоматически помечаются.
3. Extraction: cross-field validation — числа, извлечённые LLM,
   сверяются с числами в сыром тексте PDF.
4. Brief: пост-проверка rule_id — все упомянутые в резюме правила
   должны существовать в policy.json.
7. Orchestration: idempotency key — hash от application_id + policy_version + model.

Запуск:
    uv run python scripts/run_one_application_v3.py
    uv run python scripts/run_one_application_v3.py --reset
    uv run python scripts/run_one_application_v3.py --pdf data/pdf_all/abc.pdf
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


# ============================================================
# PATHS & ENV
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

load_dotenv(PROJECT_ROOT / ".env")

PDF_DIR = PROJECT_ROOT / "data" / "pdf_all"
REPORTS_DIR = PROJECT_ROOT / "data" / "reports"
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed_v3.txt"
POLICY_PATH = PROJECT_ROOT / "data" / "policy.json"
FONT_DIR = PROJECT_ROOT / "assets" / "fonts"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("underwriting")


# ============================================================
# CONFIG
# ============================================================

PROXY_API_KEY = os.getenv("PROXY_API_KEY", "")
OPENAI_COMPAT_BASE_URL = os.getenv("OPENAI_COMPAT_BASE_URL", "https://api.proxyapi.ru/v1")
MODEL = os.getenv("MODEL", "openai/gpt-6-luna")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "openai/gpt-4o-mini")
BASE_RATE = float(os.getenv("BASE_RATE", "0.18"))


# ============================================================
# LLM CLIENT
# ============================================================


def _strip_markdown(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


class LLMClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or PROXY_API_KEY
        self.base_url = base_url or OPENAI_COMPAT_BASE_URL
        if not self.api_key:
            raise ValueError("PROXY_API_KEY не задан. Проверь .env")
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    @staticmethod
    def _supports_temperature(model: str) -> bool:
        blocked_prefixes = ("openai/gpt-6", "openai/gpt-5.6", "openai/o")
        return not model.startswith(blocked_prefixes)

    def generate(self, prompt: str, model: str | None = None, max_attempts: int = 3) -> str:
        model = model or MODEL
        last_error: Exception | None = None
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._supports_temperature(model):
            kwargs["temperature"] = 0.1

        for attempt in range(1, max_attempts + 1):
            try:
                t0 = time.time()
                response = self.client.chat.completions.create(**kwargs)
                duration = time.time() - t0
                text = response.choices[0].message.content or ""
                logger.info(
                    f"LLM ok model={model} duration={duration:.2f}s "
                    f"tokens_in={response.usage.prompt_tokens} "
                    f"tokens_out={response.usage.completion_tokens}"
                )
                return text
            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                logger.warning(f"LLM attempt {attempt} failed: {e}. Retry in {wait}s")
                time.sleep(wait)

        if FALLBACK_MODEL and FALLBACK_MODEL != model:
            logger.warning(f"Fallback на {FALLBACK_MODEL}")
            return self.generate(prompt, model=FALLBACK_MODEL, max_attempts=1)

        raise RuntimeError(f"LLM failed after {max_attempts} attempts: {last_error}")

    def generate_structured(
        self, prompt: str, schema: type[BaseModel], model: str | None = None
    ) -> BaseModel:
        model = model or MODEL
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        full_prompt = (
            f"{prompt}\n\n"
            f"Отвечай ТОЛЬКО валидным JSON без markdown и пояснений.\n"
            f"Схема: {schema_json}"
        )
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                raw = self.generate(full_prompt, model=model)
                raw = _strip_markdown(raw)
                return schema.model_validate_json(raw)
            except Exception as e:
                last_error = e
                logger.warning(f"structured attempt {attempt} failed: {e}")
                time.sleep(1)
        raise RuntimeError(f"structured failed after 3 attempts: {last_error}")


# ============================================================
# SCHEMAS
# ============================================================


class ExtractedFields(BaseModel):
    application_id: str | None = None
    full_name: str | None = None
    age: int | None = None
    monthly_income: float | None = None
    monthly_debt: float | None = None
    loan_amount: float | None = None
    loan_term_months: int | None = None
    loan_purpose: str | None = None
    employment_type: str | None = None
    credit_history: str | None = None
    region: str | None = None


class RuleResult(BaseModel):
    rule_id: str
    status: str  # "pass" | "fail" | "not_applicable"
    reason: str = ""
    source_quote: str = ""
    source: str = ""  # "python" | "llm"

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: Any) -> str:
        v = str(v).strip().lower()
        if v in {"pass", "passed", "true"}:
            return "pass"
        if v in {"fail", "failed", "false"}:
            return "fail"
        if v in {"not_applicable", "na", "n/a", "unknown"}:
            return "not_applicable"
        return "not_applicable"


class SemanticRuleCheck(BaseModel):
    rule_id: str
    status: str

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: Any) -> str:
        v = str(v).strip().lower()
        if v in {"pass", "passed", "true"}:
            return "pass"
        if v in {"fail", "failed", "false"}:
            return "fail"
        return "not_applicable"


class SemanticCheckResult(BaseModel):
    checks: list[SemanticRuleCheck]


class PricingRecommendation(BaseModel):
    rate: float
    monthly_payment: float
    total_payment: float
    rationale: str


class BriefReport(BaseModel):
    application_id: str = ""
    summary: str
    key_rules: list[str] = []
    confidence: float = 0.5

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: Any) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, v))


class GraphState(TypedDict, total=False):
    application_text: str
    application_id: str
    extracted: dict
    metrics: dict
    policy_result: dict
    verdict: str
    pricing: dict | None
    brief: dict
    errors: list[str]
    idempotency_key: str


# ============================================================
# PROMPTS
# ============================================================

EXTRACTION_PROMPT = """Ты — система извлечения полей из кредитной заявки.

Задача: извлечь все поля из текста заявки. Если поля нет — оставь null.

ВАЖНО: числа извлекай ровно так, как они в тексте. Не округляй, не переставляй.
Числа вида 86,263.27 и 1,551,918.32 — это одно число, не два. Верни их как 86263.27 и 1551918.32.

ТЕКСТ ЗАЯВКИ:
{application_text}
"""

SEMANTIC_CHECK_PROMPT = """Ты — система проверки кредитной заявки на соответствие семантическим правилам политики.

ЗАЯВКА (извлечённые поля и метрики):
{application_data}

СЕМАНТИЧЕСКИЕ ПРАВИЛА (те, которые нельзя свести к формуле):
{rules}

Для каждого правила верни status:
- "pass" — правило выполнено (данные есть, условие соблюдено)
- "fail" — правило нарушено (данные есть, условие не соблюдено)
- "not_applicable" — данных для проверки нет, или правило к типу заявки не относится

ВАЖНО: если данных нет — это "not_applicable", а НЕ "fail".
"""

PRICING_PROMPT = """Ты — система выбора ставки по кредитной заявке.

ЗАЯВКА:
{application_data}

РЕЗУЛЬТАТ ПРОВЕРКИ ПОЛИТИКИ:
{policy_result}

Базовая ставка {base_rate}. Если заявка рискованная — ставка выше. Если чистая — ниже.

Верни:
- rate: ставка в долях (0.18 = 18%)
- monthly_payment: ежемесячный платёж (аннуитетный)
- total_payment: общая сумма выплат
- rationale: обоснование (1-2 предложения)
"""

BRIEF_PROMPT = """Ты — система формирования финального отчёта по заявке.

ЗАЯВКА И МЕТРИКИ:
{application_data}

ФИНАЛЬНЫЙ ВЕРДИКТ (уже определён кодом): {verdict}

РЕЗУЛЬТАТ ПРОВЕРКИ ПРАВИЛ (только сработавшие — статус fail):
{failed_rules}

Полный список rule_id, которые существуют в политике:
{all_rule_ids}

Собери краткое резюме (3-5 предложений) и выдели 3-5 ключевых правил.
Используй ТОЛЬКО rule_id из предоставленного списка. Не придумывай новые.
Не меняй вердикт — он уже зафиксирован.
"""


# ============================================================
# POLICY LOADER
# ============================================================


def load_policy() -> list[dict]:
    if not POLICY_PATH.exists():
        raise FileNotFoundError(f"Не найден {POLICY_PATH}")
    with POLICY_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        rules = raw
    elif isinstance(raw, dict) and "rules" in raw:
        rules = raw["rules"]
    else:
        raise ValueError(f"Неизвестный формат policy.json: {type(raw)}")
    if not isinstance(rules, list) or not rules:
        raise ValueError("policy.json пустой или не список правил")
    return rules


def get_policy_version() -> str:
    with POLICY_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "version" in raw:
        return str(raw["version"])
    return "1.0"


# ============================================================
# METRICS
# ============================================================


def compute_metrics(extracted: dict, base_rate: float = BASE_RATE) -> dict:
    income = extracted.get("monthly_income") or 0
    debt = extracted.get("monthly_debt") or 0
    amount = extracted.get("loan_amount") or 0
    term = extracted.get("loan_term_months") or 0

    if income <= 0 or amount <= 0 or term <= 0:
        return {
            "monthly_payment": 0.0,
            "pti": 0.0,
            "dti": 0.0,
            "note": "Недостаточно данных для расчёта",
        }

    monthly_rate = base_rate / 12
    if monthly_rate == 0:
        payment = amount / term
    else:
        factor = (1 + monthly_rate) ** term
        payment = amount * monthly_rate * factor / (factor - 1)

    pti_value = payment / income if income > 0 else 0
    dti_value = (payment + debt) / income if income > 0 else 0

    return {
        "monthly_payment": round(payment, 2),
        "pti": round(pti_value, 4),
        "dti": round(dti_value, 4),
        "note": f"Расчёт по базовой ставке {base_rate * 100:.1f}%",
    }


# ============================================================
# PYTHON RULE CHECK
# ============================================================


def check_rule_python(rule: dict, metrics: dict) -> str:
    """Проверить правило в Python.

    ВАЖНО: правило сформулировано в терминах НАРУШЕНИЯ.
    Если условие из policy.json выполняется — это fail (правило нарушено).
    Если не выполняется — pass (правило пройдено).
    """
    cond = rule.get("condition", {})
    metric = cond.get("metric")
    operator = cond.get("operator")
    value = cond.get("value")

    if metric is None or operator is None:
        return "not_applicable"

    if metric not in metrics:
        return "not_applicable"

    actual = metrics[metric]
    if actual is None:
        return "not_applicable"

    if metric in {"dti", "pti", "monthly_payment"} and actual == 0.0:
        return "not_applicable"

    try:
        violated = False
        if operator == ">":
            violated = actual > value
        elif operator == ">=":
            violated = actual >= value
        elif operator == "<":
            violated = actual < value
        elif operator == "<=":
            violated = actual <= value
        elif operator == "==":
            violated = actual == value
        elif operator == "in":
            violated = actual in value
        elif operator == "not_in":
            violated = actual not in value
        else:
            return "not_applicable"

        return "fail" if violated else "pass"
    except (TypeError, ValueError):
        return "not_applicable"


# ============================================================
# VERDICT
# ============================================================


def compute_verdict(rule_results: list[RuleResult], policy: list[dict]) -> str:
    rule_actions = {r["id"]: r.get("action", "info") for r in policy}

    has_reject = False
    has_review = False

    for r in rule_results:
        if r.status != "fail":
            continue
        action = rule_actions.get(r.rule_id, "info")
        if action == "reject":
            has_reject = True
        elif action == "review":
            has_review = True

    if has_reject:
        return "reject"
    if has_review:
        return "review"
    return "approve"


# ============================================================
# SEMANTIC RULE DETECTION
# ============================================================


def is_semantic_rule(rule: dict) -> bool:
    """Правило семантическое, если его metric не входит в известные метрики заявки."""
    cond = rule.get("condition", {})
    metric = cond.get("metric", "")
    numeric_metrics = {"dti", "pti", "age", "monthly_income", "monthly_debt",
                       "loan_amount", "loan_term_months", "monthly_payment"}
    string_metrics = {"credit_history", "employment_type", "region", "loan_purpose"}
    if metric in numeric_metrics or metric in string_metrics:
        return False
    return True


# ============================================================
# EXTRACTION VALIDATION
# ============================================================


def extract_numbers_from_text(text: str) -> list[float]:
    """Найти все числа в сыром тексте. Учитывает форматы:
    121338.79, 121,338.79, 1,551,918.32, 121 338,79.
    """
    cleaned = text
    # Шаг 1: убрать пробелы и неразрывные пробелы между цифрами
    for _ in range(5):
        cleaned = re.sub(r"(\d)[\s\u00a0]+(\d)", r"\1\2", cleaned)

    # Шаг 2: нормализовать числа с запятыми/точками
    def normalize(match: re.Match) -> str:
        s = match.group(0)
        if "." in s:
            # Американский формат: 1,551,918.32 → убрать все запятые
            return s.replace(",", "")
        if re.search(r",\d{2}$", s):
            # Русский формат: 1234567,89 → заменить запятую на точку
            return s.replace(",", ".")
        # Иначе запятые — разделители тысяч
        return s.replace(",", "")

    pattern = re.compile(r"\d[\d,.\s\u00a0]*\d|\d")
    cleaned = pattern.sub(normalize, cleaned)

    # Шаг 3: извлечь числа
    numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
    out = []
    for n in numbers:
        try:
            out.append(float(n))
        except ValueError:
            pass
    return out


def validate_extracted_numbers(extracted: dict, raw_text: str) -> list[str]:
    """Проверить, что числа из extracted есть в сыром тексте (в пределах 1%).

    НЕ обнуляет поля. Возвращает список предупреждений.
    """
    raw_numbers = extract_numbers_from_text(raw_text)
    if not raw_numbers:
        return []

    issues: list[str] = []
    numeric_fields = ["monthly_income", "monthly_debt", "loan_amount", "age", "loan_term_months"]

    for field in numeric_fields:
        value = extracted.get(field)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue

        matched = False
        for rn in raw_numbers:
            if rn == 0:
                continue
            if abs(rn - value) / max(abs(rn), 1) < 0.01:
                matched = True
                break
        if not matched:
            issues.append(f"{field}={value} не найдено в тексте PDF (low confidence)")

    return issues


# ============================================================
# AGENTS
# ============================================================


def extraction_agent(state: GraphState) -> GraphState:
    client = LLMClient()
    prompt = EXTRACTION_PROMPT.format(application_text=state["application_text"])
    try:
        result = client.generate_structured(prompt, ExtractedFields)
        app_id = result.application_id or state.get("application_id", "unknown")
        extracted = result.model_dump()

        issues = validate_extracted_numbers(extracted, state["application_text"])
        errors = state.get("errors", [])
        if issues:
            logger.warning(f"extraction validation issues: {issues}")
            errors = errors + [f"extraction_validation: {i}" for i in issues]

        logger.info(f"extraction ok for {app_id}")
        return {
            "extracted": extracted,
            "application_id": app_id,
            "errors": errors,
        }
    except Exception as e:
        logger.error(f"extraction failed: {e}")
        return {
            "extracted": {},
            "errors": state.get("errors", []) + [f"extraction: {e}"],
        }


def metrics_agent(state: GraphState) -> GraphState:
    extracted = state.get("extracted", {})
    metrics = compute_metrics(extracted)
    logger.info(
        f"metrics ok: payment={metrics.get('monthly_payment')} "
        f"pti={metrics.get('pti')} dti={metrics.get('dti')}"
    )
    return {"metrics": metrics}


def policy_check_agent(state: GraphState) -> GraphState:
    """Гибридная проверка: Python для формул, LLM для семантики."""
    rules = load_policy()
    extracted = state.get("extracted", {})
    metrics = state.get("metrics", {})

    check_data = {**extracted, **metrics}

    python_rules: list[dict] = []
    semantic_rules: list[dict] = []
    for r in rules:
        if is_semantic_rule(r):
            semantic_rules.append(r)
        else:
            python_rules.append(r)

    logger.info(
        f"policy_check: {len(python_rules)} python rules, "
        f"{len(semantic_rules)} semantic rules"
    )

    results: list[RuleResult] = []

    for r in python_rules:
        status = check_rule_python(r, check_data)
        reason = ""
        if status == "fail":
            cond = r.get("condition", {})
            metric = cond.get("metric")
            operator = cond.get("operator")
            value = cond.get("value")
            actual = check_data.get(metric)
            reason = f"{metric} = {actual}, условие нарушения: {metric} {operator} {value}"
        elif status == "not_applicable":
            reason = f"нет данных для проверки {r.get('condition', {}).get('metric')}"
        results.append(RuleResult(
            rule_id=r["id"],
            status=status,
            reason=reason,
            source="python",
        ))

    if semantic_rules:
        client = LLMClient()
        app_data = {"extracted": extracted, "metrics": metrics}
        prompt = SEMANTIC_CHECK_PROMPT.format(
            application_data=json.dumps(app_data, ensure_ascii=False, indent=2),
            rules=json.dumps(semantic_rules, ensure_ascii=False, indent=2),
        )
        try:
            llm_result = client.generate_structured(prompt, SemanticCheckResult)
            llm_map = {c.rule_id: c.status for c in llm_result.checks}
            for r in semantic_rules:
                status = llm_map.get(r["id"], "not_applicable")
                results.append(RuleResult(
                    rule_id=r["id"],
                    status=status,
                    reason="semantic check",
                    source="llm",
                ))
        except Exception as e:
            logger.error(f"semantic check failed: {e}")
            for r in semantic_rules:
                results.append(RuleResult(
                    rule_id=r["id"],
                    status="not_applicable",
                    reason=f"semantic check failed: {e}",
                    source="llm",
                ))

    covered_ids = {r.rule_id for r in results}
    missing = [r["id"] for r in rules if r["id"] not in covered_ids]
    if missing:
        logger.warning(f"missing rule_ids: {missing}")
        for rid in missing:
            results.append(RuleResult(
                rule_id=rid,
                status="not_applicable",
                reason="rule not evaluated",
                source="python",
            ))

    verdict = compute_verdict(results, rules)
    logger.info(f"policy_check ok: verdict={verdict}")

    return {
        "policy_result": {
            "rules_checked": [r.model_dump() for r in results],
        },
        "verdict": verdict,
    }


def pricing_agent(state: GraphState) -> GraphState:
    if state.get("verdict") != "approve":
        logger.info("pricing skipped: not approved")
        return {"pricing": None}

    client = LLMClient()
    application_data = {
        "extracted": state.get("extracted", {}),
        "metrics": state.get("metrics", {}),
    }
    prompt = PRICING_PROMPT.format(
        application_data=json.dumps(application_data, ensure_ascii=False, indent=2),
        policy_result=json.dumps(state.get("policy_result", {}), ensure_ascii=False, indent=2),
        base_rate=BASE_RATE,
    )
    try:
        result = client.generate_structured(prompt, PricingRecommendation)
        logger.info(f"pricing ok: rate={result.rate}")
        return {"pricing": result.model_dump()}
    except Exception as e:
        logger.error(f"pricing failed: {e}")
        return {
            "pricing": None,
            "errors": state.get("errors", []) + [f"pricing: {e}"],
        }


def brief_agent(state: GraphState) -> GraphState:
    client = LLMClient()
    rules = load_policy()
    all_rule_ids = [r["id"] for r in rules]

    rules_checked = state.get("policy_result", {}).get("rules_checked", [])
    failed_rules = [r for r in rules_checked if r.get("status") == "fail"]

    application_data = {
        "extracted": state.get("extracted", {}),
        "metrics": state.get("metrics", {}),
    }
    prompt = BRIEF_PROMPT.format(
        application_data=json.dumps(application_data, ensure_ascii=False, indent=2),
        verdict=state.get("verdict", "review"),
        failed_rules=json.dumps(failed_rules, ensure_ascii=False, indent=2),
        all_rule_ids=json.dumps(all_rule_ids, ensure_ascii=False),
    )
    try:
        result = client.generate_structured(prompt, BriefReport)
        result.application_id = state.get("application_id", "unknown")

        valid_ids = set(all_rule_ids)
        clean_rules = []
        for rid in result.key_rules:
            if rid in valid_ids:
                clean_rules.append(rid)
            else:
                logger.warning(f"brief: hallucinated rule_id '{rid}' removed")
        result.key_rules = clean_rules

        logger.info(f"brief ok for {result.application_id}")
        return {"brief": result.model_dump()}
    except Exception as e:
        logger.error(f"brief failed: {e}")
        return {
            "brief": {},
            "errors": state.get("errors", []) + [f"brief: {e}"],
        }


# ============================================================
# GRAPH
# ============================================================


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("extraction", extraction_agent)
    graph.add_node("metrics", metrics_agent)
    graph.add_node("policy_check", policy_check_agent)
    graph.add_node("pricing", pricing_agent)
    graph.add_node("brief", brief_agent)

    graph.set_entry_point("extraction")
    graph.add_edge("extraction", "metrics")
    graph.add_edge("metrics", "policy_check")
    graph.add_edge("policy_check", "pricing")
    graph.add_edge("pricing", "brief")
    graph.add_edge("brief", END)

    return graph.compile(checkpointer=MemorySaver())


# ============================================================
# IDEMPOTENCY
# ============================================================


def make_idempotency_key(app_id: str) -> str:
    payload = f"{app_id}|{get_policy_version()}|{MODEL}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ============================================================
# PDF: EXTRACTION
# ============================================================


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    import pdfplumber

    pages_text: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
    return "\n".join(pages_text)


# ============================================================
# PDF: REPORT
# ============================================================


def _register_fonts() -> tuple[str, str]:
    regular = FONT_DIR / "SourceSerifPro-Regular.ttf"
    bold = FONT_DIR / "SourceSerifPro-Bold.ttf"
    if not regular.exists():
        logger.warning(f"Шрифт не найден: {regular}. Кириллица сломается.")
        return "Helvetica", "Helvetica-Bold"
    pdfmetrics.registerFont(TTFont("SourceSerifPro", str(regular)))
    if bold.exists():
        pdfmetrics.registerFont(TTFont("SourceSerifPro-Bold", str(bold)))
    else:
        pdfmetrics.registerFont(TTFont("SourceSerifPro-Bold", str(regular)))
    return "SourceSerifPro", "SourceSerifPro-Bold"


def render_report_pdf(
    application_id: str,
    extracted: dict,
    metrics: dict,
    policy_result: dict,
    verdict: str,
    pricing: dict | None,
    brief: dict,
) -> bytes:
    font_regular, font_bold = _register_fonts()

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 60

    def line(text: str, size: int = 10, bold: bool = False, indent: int = 60, gap: int = 14):
        nonlocal y
        if y < 80:
            c.showPage()
            y = height - 60
        c.setFont(font_bold if bold else font_regular, size)
        c.drawString(indent, y, text[:110])
        y -= gap

    def divider():
        nonlocal y
        c.setStrokeColorRGB(0.7, 0.7, 0.7)
        c.line(50, y + 4, width - 50, y + 4)
        y -= 10

    line("КРЕДИТНОЕ РЕШЕНИЕ", size=18, bold=True, indent=50, gap=24)
    line(f"Номер заявки: {application_id}", size=11, indent=50, gap=16)
    line(f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}", size=10, indent=50, gap=20)
    divider()

    verdict_labels = {
        "approve": "ОДОБРЕНО",
        "reject": "ОТКАЗАНО",
        "review": "ТРЕБУЕТСЯ РУЧНАЯ ПРОВЕРКА",
        "unknown": "НЕ ОПРЕДЕЛЕНО",
    }
    line("ВЕРДИКТ", size=13, bold=True, indent=50, gap=18)
    line(verdict_labels.get(verdict, verdict.upper()), size=14, bold=True, indent=50, gap=20)
    divider()

    line("ДАННЫЕ ЗАЯВКИ", size=13, bold=True, indent=50, gap=18)
    field_labels = {
        "full_name": "ФИО",
        "age": "Возраст",
        "monthly_income": "Месячный доход",
        "monthly_debt": "Существующие платежи",
        "loan_amount": "Сумма кредита",
        "loan_term_months": "Срок",
        "loan_purpose": "Цель кредита",
        "employment_type": "Занятость",
        "credit_history": "Кредитная история",
        "region": "Регион",
    }
    for key, label in field_labels.items():
        value = extracted.get(key)
        if value is None:
            value = "—"
        elif isinstance(value, float):
            value = f"{value:,.2f}"
        line(f"{label}: {value}", size=10, indent=60, gap=13)
    y -= 6
    divider()

    line("РАСЧЁТНЫЕ МЕТРИКИ", size=13, bold=True, indent=50, gap=18)
    payment = metrics.get("monthly_payment", 0)
    pti_val = metrics.get("pti", 0)
    dti_val = metrics.get("dti", 0)
    line(f"Ежемесячный платёж (расчётный): {payment:,.2f} ₽", size=10, indent=60, gap=13)
    line(f"PTI (платёж / доход): {pti_val * 100:.2f}%", size=10, indent=60, gap=13)
    line(f"DTI (платёж + долги) / доход: {dti_val * 100:.2f}%", size=10, indent=60, gap=13)
    y -= 6
    divider()

    rules_checked = policy_result.get("rules_checked", [])
    passed_rules = [r for r in rules_checked if r.get("status") == "pass"]
    failed_rules = [r for r in rules_checked if r.get("status") == "fail"]
    na_rules = [r for r in rules_checked if r.get("status") == "not_applicable"]

    line(f"ПРОВЕРКА ПОЛИТИКИ ({len(rules_checked)} правил)", size=13, bold=True, indent=50, gap=18)
    line(
        f"Пройдено: {len(passed_rules)}    Не пройдено: {len(failed_rules)}    "
        f"Не применимо: {len(na_rules)}",
        size=10, indent=50, gap=16,
    )

    if failed_rules:
        line("НЕ ПРОЙДЕННЫЕ ПРАВИЛА:", size=11, bold=True, indent=50, gap=14)
        for r in failed_rules[:20]:
            reason = r.get("reason", "")[:90]
            source_tag = f"[{r.get('source', '?')}]"
            line(f"• {r.get('rule_id', '?')} {source_tag}: {reason}", size=10, indent=60, gap=12)
        if len(failed_rules) > 20:
            line(f"...и ещё {len(failed_rules) - 20} правил", size=10, indent=60, gap=12)
    else:
        line("Все правила пройдены или не применимы.", size=10, indent=50, gap=14)
    y -= 6
    divider()

    line("ЦЕНООБРАЗОВАНИЕ", size=13, bold=True, indent=50, gap=18)
    if pricing:
        rate = pricing.get("rate", 0)
        line(f"Ставка: {rate * 100:.2f}% годовых", size=11, indent=50, gap=14)
        line(f"Ежемесячный платёж: {pricing.get('monthly_payment', 0):,.2f} ₽", size=10, indent=50, gap=13)
        line(f"Общая сумма выплат: {pricing.get('total_payment', 0):,.2f} ₽", size=10, indent=50, gap=13)
        rationale = pricing.get("rationale", "")
        if rationale:
            line(f"Обоснование: {rationale[:100]}", size=10, indent=60, gap=13)
    else:
        line("Заявка не одобрена — финальные условия не рассчитываются.", size=10, indent=60, gap=14)
        line(f"Расчётный платёж по базовой ставке: {payment:,.2f} ₽/мес", size=10, indent=60, gap=13)
    y -= 6
    divider()

    line("РЕЗЮМЕ", size=13, bold=True, indent=50, gap=18)
    summary = brief.get("summary", "")
    words = summary.split()
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 > 100:
            line(current_line, size=10, indent=60, gap=13)
            current_line = word
        else:
            current_line = f"{current_line} {word}".strip()
    if current_line:
        line(current_line, size=10, indent=60, gap=13)

    y -= 10
    confidence = brief.get("confidence", 0)
    line(f"Уверенность системы: {confidence * 100:.0f}%", size=10, indent=50, gap=14)

    c.save()
    buffer.seek(0)
    return buffer.read()


# ============================================================
# PROCESSED TRACKING
# ============================================================


def load_processed() -> set[str]:
    if not PROCESSED_FILE.exists():
        return set()
    return set(
        line.strip()
        for line in PROCESSED_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def mark_processed(app_id: str) -> None:
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PROCESSED_FILE.open("a", encoding="utf-8") as f:
        f.write(app_id + "\n")


def pick_random_unprocessed() -> Path:
    if not PDF_DIR.exists():
        raise FileNotFoundError(f"Папка не найдена: {PDF_DIR}")
    processed = load_processed()
    all_pdfs = list(PDF_DIR.glob("*.pdf"))
    unprocessed = [p for p in all_pdfs if p.stem not in processed]
    if not unprocessed:
        raise RuntimeError(
            "Все заявки обработаны. Удали data/processed_v3.txt, чтобы начать заново."
        )
    return random.choice(unprocessed)


# ============================================================
# CLI
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="Обработка одной случайной заявки (v3)")
    parser.add_argument("--pdf", type=str, help="Путь к конкретному PDF (по умолчанию случайный)")
    parser.add_argument("--reset", action="store_true", help="Сбросить processed_v3.txt")
    args = parser.parse_args()

    if args.reset:
        if PROCESSED_FILE.exists():
            PROCESSED_FILE.unlink()
            print("processed_v3.txt сброшен")
        return 0

    try:
        if args.pdf:
            pdf_path = Path(args.pdf)
        else:
            pdf_path = pick_random_unprocessed()
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Ошибка: {e}")
        return 1

    app_id = pdf_path.stem
    print(f"Выбрана заявка: {app_id}")
    print(f"Файл: {pdf_path}")
    print()

    pdf_bytes = pdf_path.read_bytes()
    application_text = extract_text_from_pdf(pdf_bytes)
    print(f"Извлечено текста: {len(application_text)} символов")
    print()

    graph = build_graph()
    idem_key = make_idempotency_key(app_id)
    print(f"Idempotency key: {idem_key}")
    print()

    initial_state: GraphState = {
        "application_text": application_text,
        "application_id": app_id,
        "errors": [],
        "idempotency_key": idem_key,
    }
    config = {"configurable": {"thread_id": idem_key}}

    print("Прогон через мультиагентный пайплайн...")
    try:
        result = graph.invoke(initial_state, config=config)
    except Exception as e:
        print(f"Ошибка пайплайна: {e}")
        return 2

    extracted = result.get("extracted", {})
    metrics = result.get("metrics", {})
    policy_result = result.get("policy_result", {})
    verdict = result.get("verdict", "review")
    pricing = result.get("pricing")
    brief = result.get("brief", {})
    errors = result.get("errors", [])

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_bytes = render_report_pdf(
        app_id, extracted, metrics, policy_result, verdict, pricing, brief
    )
    report_path = REPORTS_DIR / f"{app_id}_v3_report.pdf"
    report_path.write_bytes(report_bytes)

    mark_processed(app_id)

    rules_checked = policy_result.get("rules_checked", [])
    failed_count = sum(1 for r in rules_checked if r.get("status") == "fail")
    na_count = sum(1 for r in rules_checked if r.get("status") == "not_applicable")
    pass_count = sum(1 for r in rules_checked if r.get("status") == "pass")

    print()
    print("=" * 60)
    print(f"Вердикт: {verdict.upper()}")
    print(f"Правил проверено: {len(rules_checked)} (pass={pass_count}, fail={failed_count}, na={na_count})")
    print(f"Расчётный платёж: {metrics.get('monthly_payment', 0):,.2f} ₽/мес")
    print(f"PTI: {metrics.get('pti', 0) * 100:.2f}%")
    print(f"DTI: {metrics.get('dti', 0) * 100:.2f}%")
    if pricing:
        print(f"Ставка: {pricing.get('rate', 0) * 100:.2f}%")
    print(f"Отчёт сохранён: {report_path}")
    print("=" * 60)

    if errors:
        print()
        print(f"Предупреждения ({len(errors)}):")
        for e in errors[:5]:
            print(f"  - {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
