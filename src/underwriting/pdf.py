"""
PDF-генерация и парсинг кредитных заявок.

Используется в extraction-агенте (фаза 2) для чтения PDF и в генераторе
тестовых данных (фаза 1.3) для создания документов.
"""
import io
import logging
from pathlib import Path

import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .schemas import Application

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
FONT_REGULAR = FONT_DIR / "SourceSerifPro-Regular.ttf"
FONT_BOLD = FONT_DIR / "SourceSerifPro-Bold.ttf"


def _register_fonts() -> tuple[str, str]:
    """Зарегистрировать шрифты с поддержкой кириллицы. Вернуть (regular, bold)."""
    if not FONT_REGULAR.exists():
        logger.warning("Шрифт не найден: %s. Использую Helvetica (кириллица сломается).", FONT_REGULAR)
        return "Helvetica", "Helvetica-Bold"

    pdfmetrics.registerFont(TTFont("SourceSerifPro", str(FONT_REGULAR)))
    if FONT_BOLD.exists():
        pdfmetrics.registerFont(TTFont("SourceSerifPro-Bold", str(FONT_BOLD)))
    else:
        pdfmetrics.registerFont(TTFont("SourceSerifPro-Bold", str(FONT_REGULAR)))
    return "SourceSerifPro", "SourceSerifPro-Bold"


def application_to_pdf(application: Application) -> bytes:
    """Превратить объект Application в PDF-документ (байты)."""
    font_regular, font_bold = _register_fonts()

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 72
    c.setFont(font_bold, 20)
    c.drawString(72, y, "Кредитная заявка")
    y -= 32

    c.setFont(font_regular, 11)
    c.drawString(72, y, f"Номер заявки: {application.application_id}")
    y -= 16

    fields = [
        ("ФИО", application.full_name),
        ("Возраст", f"{application.age} лет"),
        ("Месячный доход", f"{application.monthly_income:,.2f} ₽"),
        ("Существующие платежи", f"{application.monthly_debt:,.2f} ₽"),
        ("Сумма кредита", f"{application.loan_amount:,.2f} ₽"),
        ("Срок", f"{application.loan_term_months} месяцев"),
        ("Цель кредита", application.loan_purpose.value),
        ("Занятость", application.employment_type.value),
        ("Кредитная история", application.credit_history.value),
        ("Регион", application.region.value),
        ("Дата подачи", application.applied_at.strftime("%d.%m.%Y")),
    ]

    for label, value in fields:
        c.setFont(font_bold, 11)
        c.drawString(72, y, f"{label}:")
        c.setFont(font_regular, 11)
        c.drawString(260, y, str(value))
        y -= 18

    c.save()
    buffer.seek(0)
    return buffer.read()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Извлечь весь текст из PDF (все страницы, склеенные через \\n)."""
    pages_text: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
    return "\n".join(pages_text)
