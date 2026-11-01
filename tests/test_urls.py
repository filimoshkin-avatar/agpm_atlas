import json

from atlas import REFERENCE_JSON
from atlas.urls import normalize_url, outlet_from_url


def test_scheme_host_www_and_trailing_slash():
    assert normalize_url("http://WWW.Example.COM/Path/") == "https://example.com/Path"


def test_fragment_and_tracking_parameters_are_dropped():
    raw = "https://ex.com/a?utm_source=x&b=2&fbclid=1&gclid=2&yclid=3&mc_cid=4&mc_eid=5&ref=6&a=1#top"
    assert normalize_url(raw) == "https://ex.com/a?a=1&b=2"


def test_tracking_match_is_whole_key_not_prefix():
    # «referrer» и «reference» — не параметр отслеживания «ref».
    assert normalize_url("https://ex.com/?referrer=a&reference=b") == "https://ex.com?reference=b&referrer=a"


def test_remaining_parameters_are_sorted_and_blank_values_kept():
    assert normalize_url("https://ex.com/p?z=1&a=&m=2") == "https://ex.com/p?a=&m=2&z=1"


def test_root_path_collapses():
    assert normalize_url("https://ex.com/") == normalize_url("https://ex.com")


def test_october_urls_stay_unique_after_normalization():
    data = json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))
    normalized = [normalize_url(m["u"]) for m in data["mats"].values()]
    assert len(normalized) == 794
    assert len(set(normalized)) == 794
    assert all(u.startswith("https://") for u in normalized)


def test_outlet_is_domain_without_www():
    assert outlet_from_url("https://www.Zdnet.com/article/x") == "zdnet.com"
