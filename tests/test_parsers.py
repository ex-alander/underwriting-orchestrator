"""Тесты парсеров кредитной политики."""
from underwriting.parsers import extract_rules_from_html, extract_rules_from_urls, fetch_html
from underwriting.schemas import ParsedRule


def test_fetch_html_returns_empty_on_bad_url():
    """Несуществующий домен → пустая строка, без падения."""
    html = fetch_html("https://this-domain-does-not-exist-12345.ru", timeout=3)
    assert html == ""


def test_fetch_html_returns_empty_on_empty_url():
    """Пустой URL → пустая строка."""
    html = fetch_html("", timeout=3)
    assert html == ""


def test_extract_rules_from_html_finds_candidates():
    """Синтетический HTML с явными правилами → кандидаты найдены."""
    html = """
    <html><body>
      <p>Минимальный возраст заёмщика — 21 год.</p>
      <p>Совсем не правило, просто текст без ключевых слов.</p>
      <li>Максимальный DTI — 50%.</li>
      <p>Требуется стаж на последнем месте не менее 6 месяцев.</p>
      <h3>Доход должен быть не менее 20 000 рублей в месяц.</h3>
    </body></html>
    """
    rules = extract_rules_from_html(html, "https://test.example/policy")

    assert len(rules) >= 3
    texts = [r.raw_text for r in rules]
    assert any("возраст" in t.lower() for t in texts)
    assert any("DTI" in t for t in texts)
    assert any("доход" in t.lower() for t in texts)


def test_extract_rules_attaches_source_url():
    """Каждый кандидат знает, с какой страницы он пришёл."""
    html = "<p>Минимальный возраст 21 год.</p>"
    rules = extract_rules_from_html(html, "https://sber.ru/credit")
    assert len(rules) == 1
    assert rules[0].source_url == "https://sber.ru/credit"
    assert isinstance(rules[0], ParsedRule)


def test_extract_rules_ignores_empty_html():
    """Пустая строка → пустой список."""
    assert extract_rules_from_html("", "https://test.example") == []


def test_extract_rules_ignores_short_and_long_text():
    """Слишком короткие и слишком длинные фрагменты отсекаются."""
    html = """
    <p>возраст</p>
    <p>доход</p>
    <p>""" + "доход " * 200 + """</p>
    """
    rules = extract_rules_from_html(html, "https://test.example")
    assert rules == []


def test_extract_rules_deduplicates():
    """Одинаковый текст дважды → один кандидат."""
    html = """
    <p>Минимальный возраст заёмщика — 21 год.</p>
    <p>Минимальный возраст заёмщика — 21 год.</p>
    """
    rules = extract_rules_from_html(html, "https://test.example")
    assert len(rules) == 1


def test_extract_rules_from_urls_aggregates():
    """Несколько URL → единый список кандидатов."""
    urls = [
        "https://this-domain-does-not-exist-12345.ru",
        "https://this-domain-also-not-exists-67890.ru",
    ]
    rules = extract_rules_from_urls(urls, verify=False)
    # Оба URL недоступны — список пустой, но функция не падает
    assert rules == []


def test_extract_rules_from_urls_handles_empty_list():
    """Пустой список URL → пустой список кандидатов."""
    assert extract_rules_from_urls([]) == []