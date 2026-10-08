"""Сгенерировать 30 заявок и сохранить в data/applications.jsonl."""
import json
from pathlib import Path

from underwriting.generate import generate_batch


def main():
    apps = generate_batch(30)
    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "applications.jsonl"

    with out_file.open("w", encoding="utf-8") as f:
        for app in apps:
            f.write(json.dumps(app.model_dump(mode="json"), ensure_ascii=False) + "\n")

    print(f"Сохранено {len(apps)} заявок в {out_file}")


if __name__ == "__main__":
    main()
