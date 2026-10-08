"""Тесты PDF-генерации и парсинга."""
from datetime import date

from underwriting.pdf import application_to_pdf, extract_text_from_pdf
from underwriting.schemas import (
    Application, CreditHistory, EmploymentType, LoanPurpose, Region,
)


def _make_application() -> Application:
    return Application(
        application_id="test-pdf-001",
        full_name="Иванов Иван Иванович",
        age=35,
        monthly_income=80_000,
        monthly_debt=5_000,
        loan_amount=500_000,
        loan_term_months=36,
        loan_purpose=LoanPurpose.CONSUMER,
        employment_type=EmploymentType.EMPLOYED,
        credit_history=CreditHistory.CLEAN,
        region=Region.MOSCOW,
        applied_at=date(2026, 10, 7),
    )


def test_pdf_generated():
    pdf_bytes = application_to_pdf(_make_application())
    assert pdf_bytes[:4] == b"%PDF"


def test_round_trip_contains_all_fields():
    pdf_bytes = application_to_pdf(_make_application())
    text = extract_text_from_pdf(pdf_bytes)
    assert "test-pdf-001" in text
    assert "Иванов Иван Иванович" in text
    assert "500,000.00" in text
    assert "36 месяцев" in text


def test_empty_pdf_returns_empty_text():
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.save()
    empty_bytes = buf.getvalue()

    assert extract_text_from_pdf(empty_bytes) == ""


def test_cyrillic_is_preserved():
    pdf_bytes = application_to_pdf(_make_application())
    text = extract_text_from_pdf(pdf_bytes)
    # Если шрифт не поддерживает кириллицу — русские буквы пропадут или станут вопросительными знаками
    assert "Кредитная заявка" in text
    assert "?????" not in text