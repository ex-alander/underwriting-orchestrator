"""
CLI для полного пайплайна кредитного андеррайтинга. Версия 2.

Что нового по сравнению с v1:
1. Добавлен шаг compute_metrics между extraction и policy_check.
   Метрики (monthly_payment, pti, dti) считаются в Python, а не LLM.
2. Вердикт (approve/reject/review) собирается детерминированно в Python.
   LLM только проверяет правила, финальное решение — код.
3. Промпт policy_check просит краткие объяснения (1 предложение на правило).
4. В отчёте показывается расчётный платёж даже при reject.

Запуск:
    uv run python scripts/run_one_application_v2.py
    uv run python scripts/run_one_application_v2.py --reset
    uv run python scripts/run_one_application_v2.py --pdf data/pdf_all/abc.pdf
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import random
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
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed_v2.txt"
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
    """Обёртка над OpenAI SDK через ProxyAPI: retry, fallback, structured output."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or PROXY_API_KEY
        self.base_url = base_url or OPENAI_COMPAT_BASE_URL
        if not self.api_key:
            raise ValueError("PROXY_API_KEY не задан. Проверь .env")
        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

    @staticmethod
    def _supports_temperature(model: str) -> bool:
        """GPT-6, GPT-5.6 и reasoning-модели не поддерживают temperature."""
        blocked_prefixes = ("openai/gpt-6", "openai/gpt-5.6", "openai/o")
        return not model.startswith(blocked_prefixes)

    def generate(
        self, prompt: str, model: str | None = None, max_attempts: int = 3
    ) -> str:
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
    passed: bool
    reason: str = ""
    source_quote: str = ""


class PolicyCheckResult(BaseModel):
    rules_checked: list[RuleResult]
    confidence: float = 0.5

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: Any) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, v))


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


# ============================================================
# PROMPTS
# ============================================================

EXTRACTION_PROMPT = """Ты — система извлечения полей из кредитной заявки.

Задача: извлечь все поля из текста заявки. Если поля нет — оставь null.

ТЕКСТ ЗАЯВКИ:
{application_text}
"""

POLICY_CHECK_PROMPT = """Ты — система проверки кредитной заявки на соответствие правилам политики.

ЗАЯВКА (извлечённые поля и вычисленные метрики):
{application_data}

ПРАВИЛА ПОЛИТИКИ (JSON):
{rules}

Задача: для каждого правила определить, пройдено ли оно (passed = true / false).

ВАЖНО:
- Метрики (monthly_payment, pti, dti) уже вычислены и точны. Используй их как есть.
- Объяснение (reason) — одно короткое предложение, не больше.
- source_quote — короткая цитата из правила (до 15 слов).
- Не выдумывай новые правила. Проверяй только те, что переданы.
- Не определяй финальный вердикт. Только проверь каждое правило.
"""

PRICING_PROMPT = """Ты — система расчёта ставки по кредитной заявке.

ЗАЯВКА:
{application_data}

РЕЗУЛЬТАТ ПРОВЕРКИ ПОЛИТИКИ:
{policy_result}

Базовая ставка {base_rate}. Если заявка рискованная — ставка выше. Если чистая — ниже.

Верни:
- rate: ставка в долях (0.18 = 18%)
- monthly_payment: ежемесячный платёж
- total_payment: общая сумма выплат
- rationale: обоснование (1-2 предложения)
"""

BRIEF_PROMPT = """Ты — система формирования финального отчёта по заявке.

ЗАЯВКА И МЕТРИКИ:
{application_data}

ФИНАЛЬНЫЙ ВЕРДИКТ (уже определён кодом): {verdict}

ПРАВИЛА (JSON):
{policy_result}

ПРАЙСИНГ:
{pricing}

Собери краткое резюме (3-5 предложений) и выдели 3-5 ключевых правил.
Не меняй вердикт — он уже зафиксирован.
"""


# ============================================================
# POLICY LOADER
# ============================================================


def load_policy() -> list[dict]:
    """Загрузить правила политики с явной проверкой формата."""
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


# ============================================================
# METRICS
# ============================================================


def compute_metrics(extracted: dict, base_rate: float = BASE_RATE) -> dict:
    """Вычислить метрики заявки в Python, без LLM."""
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
# VERDICT
# ============================================================


def compute_verdict(rules_checked: list[dict], policy: list[dict]) -> str:
    """Детерминированно определить вердикт по результатам проверки правил.

    Логика:
    - Если хотя бы одно непройденное правило имеет action = reject → reject.
    - Иначе если есть непройденные с action = review → review.
    - Иначе → approve.
    """
    rule_actions = {r["id"]: r.get("action", "info") for r in policy}

    has_reject = False
    has_review = False

    for r in rules_checked:
        if r.get("passed", True):
            continue
        action = rule_actions.get(r.get("rule_id", ""), "info")
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
# AGENTS
# ============================================================


def extraction_agent(state: GraphState) -> GraphState:
    client = LLMClient()
    prompt = EXTRACTION_PROMPT.format(application_text=state["application_text"])
    try:
        result = client.generate_structured(prompt, ExtractedFields)
        app_id = result.application_id or state.get("application_id", "unknown")
        logger.info(f"extraction ok for {app_id}")
        return {"extracted": result.model_dump(), "application_id": app_id}
    except Exception as e:
        logger.error(f"extraction failed: {e}")
        return {
            "extracted": {},
            "errors": state.get("errors", []) + [f"extraction: {e}"],
        }


def metrics_agent(state: GraphState) -> GraphState:
    """Вычисляет метрики заявки в Python. Без LLM."""
    extracted = state.get("extracted", {})
    metrics = compute_metrics(extracted)
    logger.info(
        f"metrics ok: payment={metrics.get('monthly_payment')} "
        f"pti={metrics.get('pti')} dti={metrics.get('dti')}"
    )
    return {"metrics": metrics}


def policy_check_agent(state: GraphState) -> GraphState:
    client = LLMClient()
    rules = load_policy()
    rules_subset = rules

    application_data = {
        "extracted": state.get("extracted", {}),
        "metrics": state.get("metrics", {}),
    }

    logger.info(f"policy_check with {len(rules_subset)} rules")
    prompt = POLICY_CHECK_PROMPT.format(
        application_data=json.dumps(application_data, ensure_ascii=False, indent=2),
        rules=json.dumps(rules_subset, ensure_ascii=False, indent=2),
    )
    try:
        result = client.generate_structured(prompt, PolicyCheckResult)
        if not result.rules_checked:
            raise ValueError("policy_check вернул 0 проверенных правил")
        rules_as_dicts = [r.model_dump() for r in result.rules_checked]
        verdict = compute_verdict(rules_as_dicts, rules)
        logger.info(f"policy_check ok: verdict={verdict}")

        return {
            "policy_result": {
                "rules_checked": [r.model_dump() for r in result.rules_checked],
                "confidence": result.confidence,
            },
            "verdict": verdict,
        }
    except Exception as e:
        logger.error(f"policy_check failed: {e}")
        return {
            "policy_result": {"rules_checked": [], "confidence": 0.0},
            "verdict": "review",
            "errors": state.get("errors", []) + [f"policy_check: {e}"],
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
    application_data = {
        "extracted": state.get("extracted", {}),
        "metrics": state.get("metrics", {}),
    }
    prompt = BRIEF_PROMPT.format(
        application_data=json.dumps(application_data, ensure_ascii=False, indent=2),
        verdict=state.get("verdict", "review"),
        policy_result=json.dumps(state.get("policy_result", {}), ensure_ascii=False, indent=2),
        pricing=json.dumps(state.get("pricing"), ensure_ascii=False, indent=2),
    )
    try:
        result = client.generate_structured(prompt, BriefReport)
        result.application_id = state.get("application_id", "unknown")
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
# PDF: REPORT GENERATION
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
    note = metrics.get("note", "")
    if note:
        line(f"Примечание: {note}", size=9, indent=60, gap=12)
    y -= 6
    divider()

    rules_checked = policy_result.get("rules_checked", [])
    passed_rules = [r for r in rules_checked if r.get("passed")]
    failed_rules = [r for r in rules_checked if not r.get("passed")]
    line(f"ПРОВЕРКА ПОЛИТИКИ ({len(rules_checked)} правил)", size=13, bold=True, indent=50, gap=18)
    line(f"Пройдено: {len(passed_rules)}    Не пройдено: {len(failed_rules)}", size=10, indent=50, gap=16)

    if failed_rules:
        line("НЕ ПРОЙДЕННЫЕ ПРАВИЛА:", size=11, bold=True, indent=50, gap=14)
        for r in failed_rules[:15]:
            reason = r.get("reason", "")[:90]
            line(f"• {r.get('rule_id', '?')}: {reason}", size=10, indent=60, gap=12)
        if len(failed_rules) > 15:
            line(f"...и ещё {len(failed_rules) - 15} правил", size=10, indent=60, gap=12)
    else:
        line("Все правила пройдены.", size=10, indent=50, gap=14)
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
            "Все заявки обработаны. Удали data/processed_v2.txt, чтобы начать заново."
        )
    return random.choice(unprocessed)


# ============================================================
# CLI
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(description="Обработка одной случайной заявки (v2)")
    parser.add_argument("--pdf", type=str, help="Путь к конкретному PDF (по умолчанию случайный)")
    parser.add_argument("--reset", action="store_true", help="Сбросить processed_v2.txt")
    args = parser.parse_args()

    if args.reset:
        if PROCESSED_FILE.exists():
            PROCESSED_FILE.unlink()
            print("processed_v2.txt сброшен")
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
    initial_state: GraphState = {
        "application_text": application_text,
        "application_id": app_id,
        "errors": [],
    }
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

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
    report_path = REPORTS_DIR / f"{app_id}_v2_report.pdf"
    report_path.write_bytes(report_bytes)

    mark_processed(app_id)

    print()
    print("=" * 60)
    print(f"Вердикт: {verdict.upper()}")
    print(f"Правил проверено: {len(policy_result.get('rules_checked', []))}")
    print(f"Расчётный платёж: {metrics.get('monthly_payment', 0):,.2f} ₽/мес")
    print(f"PTI: {metrics.get('pti', 0) * 100:.2f}%")
    print(f"DTI: {metrics.get('dti', 0) * 100:.2f}%")
    if pricing:
        print(f"Ставка: {pricing.get('rate', 0) * 100:.2f}%")
    print(f"Отчёт сохранён: {report_path}")
    print("=" * 60)

    if errors:
        print()
        print(f"Ошибки в пайплайне ({len(errors)}):")
        for e in errors[:5]:
            print(f"  - {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
