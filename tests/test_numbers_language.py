from atlas.language import fix, violations
from atlas.numbers import missing


def test_number_spellings_match():
    source = "Revenue grew 1.4 million; adoption 35-60 percent; 1,000 agents; in 2026 the team of 13 agents."
    assert missing("1,4 млн; 35–60%; 1 000 агентов; 13 агентов", source) == []


def test_missing_number_is_reported():
    assert missing("сократили на 75%", "reduced by 70 percent") == ["75"]


def test_numbers_found_in_radar_card_count_too():
    assert missing("за 2,5 месяца", "нет цифр", "внедрила за 2,5 месяца") == []


def test_year_and_count_are_separate_atoms():
    assert missing("в 2026 году 15 агентов", "15 agents launched in 2026") == []


def test_quotes_and_spaces_are_fixed():
    assert fix('Компания "Эрегион" и "вложенные "лапки" тут"') == "Компания «Эрегион» и «вложенные „лапки“ тут»"
    assert fix("1 000 задач, 35-60%") == "1 000 задач, 35–60%"


def test_forbidden_words_and_turns():
    text = "Это важный шаг. Здесь агент ключевой. Это не продукт, а сервис."
    found = violations(text)
    assert any("важный" in f for f in found) and any("ключевой" in f for f in found)
    assert any("это не X, а Y" in f for f in found)
    assert sum("начинается" in f for f in found) == 3
    assert violations("Агент готовит черновик, человек утверждает.") == []


def test_english_number_words_count_as_numbers():
    assert missing("в ближайшие 6–12 месяцев", "over the next six to 12 months") == []
    assert missing("6 сессий трека", "The track features six sessions") == []
    assert missing("7 сессий", "six sessions") == ["7"]
