from aurora.identity_core import _context_entities


def evidence(
    item_id: str,
    url: str,
    text: str,
    *,
    reliability: float = 0.58,
    direct_match: bool = True,
) -> dict:
    return {
        "id": item_id,
        "source": "test",
        "source_url": url,
        "title": text,
        "excerpt": text,
        "reliability": reliability,
        "direct_match": direct_match,
        "content_hash": item_id,
    }


def test_context_name_confirmed_by_two_independent_domains():
    items = [
        evidence(
            "ev1",
            "https://example.org/a",
            "Илья Черданцев +79990000000",
        ),
        evidence(
            "ev2",
            "https://example.net/b",
            "Контакты: Илья Черданцев",
        ),
    ]

    entities, rows = _context_entities(
        {"name": "Илья Черданцев"}, items, []
    )

    assert len(entities) == 1
    assert rows[0]["status"] == "confirmed"
    assert rows[0]["independent_source_count"] == 2
    assert rows[0]["confidence"] >= 80


def test_context_username_uses_token_boundaries():
    items = [
        evidence(
            "ev1",
            "https://example.org/a",
            "Профиль @aurora_user",
            reliability=0.8,
        ),
        evidence(
            "ev2",
            "https://example.net/b",
            "Совпадение aurora_user_extra не должно засчитываться",
        ),
    ]

    _, rows = _context_entities(
        {"username": "@aurora_user"}, items, []
    )

    assert rows[0]["status"] == "partially_confirmed"
    assert rows[0]["source_count"] == 1


def test_context_without_public_support_is_insufficient():
    _, rows = _context_entities(
        {"city": "Москва"}, [], []
    )

    assert rows[0]["status"] == "insufficient"
    assert rows[0]["confidence"] == 25
    assert rows[0]["independent_source_count"] == 0


def test_high_confidence_alternative_name_creates_conflict():
    person_entities = [
        {
            "id": "person_other",
            "type": "person",
            "claims": [
                {
                    "field": "fio_candidate",
                    "value": "Пётр Иванов",
                    "normalized_value": "пётр иванов",
                    "confidence": 84,
                    "independent_source_count": 2,
                }
            ],
        }
    ]

    _, rows = _context_entities(
        {"name": "Илья Черданцев"}, [], person_entities
    )

    assert rows[0]["status"] == "conflict"
    assert rows[0]["conflicting_value"] == "Пётр Иванов"
    assert rows[0]["confidence"] == 20
