from atlas import REFERENCE_HTML
from atlas.card_lines import extract


def test_card_lines_match_prototype_for_all_27_cards(reference, prototype_data):
    shorts = {key: item["short"] for key, item in reference["items"].items()}
    cards = extract(REFERENCE_HTML, shorts)
    assert set(cards) == set(reference["items"])
    for item in prototype_data["items"]:
        assert cards[item["key"]]["card_line"] == item["card_line"], item["key"]
        assert cards[item["key"]]["card_title"] == item["card_title"], item["key"]
