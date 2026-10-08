"""Парсеры открытых источников: правила кредитной политики."""
import logging
from time import sleep

import requests
from bs4 import BeautifulSoup

from .schemas import ParsedRule

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

KEYWORDS = ["возраст", "доход", "стаж", "просрочк", "DTI", "PTI", "%", "руб"]


def fetch_html(url: str, timeout: int = 10, verify: bool | str = True) -> str:
    """Скачать HTML по URL. Возвращает пустую строку при ошибке."""
    for attempt in range(3):
        try:
            response = requests.get(
                url, headers=HEADERS, timeout=timeout, verify=verify
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.warning("Попытка %d не удалась для %s: %s", attempt + 1, url, e)
            if attempt < 2:
                sleep(1.5)
    return ""


def extract_rules_from_html(html: str, source_url: str) -> list[ParsedRule]:
    """Вытащить строки, похожие на правила политики, из HTML."""
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    found: list[ParsedRule] = []
    seen: set[str] = set()

    for tag in soup.find_all(["p", "li", "h3", "h4"]):
        text = tag.get_text(strip=True)
        if not text or len(text) < 15 or len(text) > 400:
            continue
        if text in seen:
            continue
        if any(k.lower() in text.lower() for k in KEYWORDS):
            seen.add(text)
            found.append(ParsedRule(source_url=source_url, raw_text=text))

    return found


def extract_rules_from_urls(
    urls: list[str], verify: bool | str = True
) -> list[ParsedRule]:
    """Скачать HTML со списка URL и извлечь кандидатов в правила."""
    result: list[ParsedRule] = []
    for url in urls:
        html = fetch_html(url, verify=verify)
        if not html:
            logger.warning("Пропускаю %s — пустой HTML", url)
            continue
        result.extend(extract_rules_from_html(html, url))
    return result