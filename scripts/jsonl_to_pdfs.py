"""
Конвертер applications.jsonl → 100 PDF-заявок.

Читает data/applications.jsonl, для каждой заявки вызывает application_to_pdf
из src/underwriting/pdf.py и сохраняет в data/pdf_all/{application_id}.pdf.

Запуск:
    uv run python scripts/jsonl_to_pdfs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Добавляем src/ в путь, чтобы импортировать underwriting
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from underwriting.pdf import application_to_pdf  # noqa: E402
from underwriting.schemas import Application  # noqa: E402


INPUT_PATH = PROJECT_ROOT / "data" / "applications.jsonl"
OUTPUT_DIR = PROJECT_ROOT / "data" / "pdf_all"


def main() -> int:
    if not INPUT_PATH.exists():
        print(f"Не найден файл: {INPUT_PATH}")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    saved = 0
    errors: list[str] = []

    with INPUT_PATH.open(encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                data = json.loads(line)
                app = Application.model_validate(data)
                pdf_bytes = application_to_pdf(app)
                out_path = OUTPUT_DIR / f"{app.application_id}.pdf"
                out_path.write_bytes(pdf_bytes)
                saved += 1
                if saved % 10 == 0:
                    print(f"  сохранено {saved}/{total}...")
            except Exception as e:
                errors.append(f"Строка {i}: {e}")

    print()
    print(f"Всего заявок: {total}")
    print(f"Сохранено PDF: {saved}")
    print(f"Ошибок: {len(errors)}")
    print(f"Папка: {OUTPUT_DIR}")

    if errors:
        print()
        print("Первые 5 ошибок:")
        for e in errors[:5]:
            print(f"  - {e}")

    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
