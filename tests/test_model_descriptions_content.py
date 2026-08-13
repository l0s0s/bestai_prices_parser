import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load(name):
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


def test_every_description_entry_has_required_nonempty_fields():
    data = _load("model_descriptions.json")
    assert data, "config/model_descriptions.json should not be empty"
    for canonical_id, entry in data.items():
        assert entry.get("display_name", "").strip(), f"{canonical_id} missing display_name"
        assert entry.get("description_ru", "").strip(), f"{canonical_id} missing description_ru"
        assert entry.get("description_en", "").strip(), f"{canonical_id} missing description_en"


def test_every_description_key_is_a_known_canonical_id():
    """Catches typo'd canonical ids: every key must be a real value somewhere
    in config/model_aliases.json (the universe of ids normalize_model_name()
    can ever produce). Deliberately does NOT require full coverage of that
    universe — scope is intentionally the currently-published subset."""
    descriptions = _load("model_descriptions.json")
    aliases = _load("model_aliases.json")
    known_ids = set(aliases.values())
    unknown = set(descriptions.keys()) - known_ids
    assert not unknown, f"Typo'd canonical ids not in model_aliases.json: {unknown}"
