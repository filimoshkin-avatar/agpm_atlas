import copy
import json

import pytest

from atlas import PROTOTYPE, REFERENCE_JSON


@pytest.fixture(scope="session")
def _prototype_data():
    raw = (PROTOTYPE / "data" / "atlas-2026-10-09.js").read_text(encoding="utf-8")
    prefix = "window.ATLAS_DATA = "
    assert raw.startswith(prefix)
    return json.loads(raw[len(prefix):].rstrip().rstrip(";"))


@pytest.fixture
def prototype_data(_prototype_data):
    """Данные прототипа в модели задания — то, что должен показать сайт."""
    return copy.deepcopy(_prototype_data)


@pytest.fixture(scope="session")
def reference():
    return json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))
