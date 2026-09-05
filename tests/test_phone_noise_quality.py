from aurora import deep_public
from aurora import identity_core


def test_reverse_phone_catalog_is_noise():
    assert identity_core._is_noise(
        "https://kto-zvonil-mne.ru/phone/9308101777",
        "Кто звонил с +79308101777 отзывы оператор номера",
    )
    assert identity_core._is_noise(
        "https://secab.ru/audit/79308101777",
        "+79308101777 чей звонок мошенники",
    )


def test_low_signal_phone_page_does_not_produce_identity_entities():
    page = {
        "id": "ev_page_low",
        "source": "deep_public_page",
        "source_url": "https://kto-zvonil-mne.ru/phone/9308101777",
        "source_type": "public_page",
        "title": "Кто звонил",
        "excerpt": "Телефон +79308101777. Андрей Иванов. ПАО МегаФон.",
        "reliability": 0.76,
        "direct_match": True,
        "content_hash": "low",
        "metadata": {
            "identity_eligible": False,
            "source_quality": "low",
            "extracted_emails": [],
            "extracted_names": ["Андрей Иванов"],
            "extracted_organisations": ["ПАО МегаФон"],
            "social_profiles": [],
        },
    }
    case = {"entities": []}
    assert deep_public._entities_from_pages(case, [page]) == []


def test_high_signal_page_can_produce_candidate():
    page = {
        "id": "ev_page_high",
        "source": "deep_public_page",
        "source_url": "https://example.org/contacts",
        "source_type": "public_page",
        "title": "Контакты",
        "excerpt": "Иван Петров +79308101777 owner@example.org",
        "reliability": 0.82,
        "direct_match": True,
        "content_hash": "high",
        "metadata": {
            "identity_eligible": True,
            "source_quality": "high",
            "extracted_emails": ["owner@example.org"],
            "extracted_names": ["Иван Петров"],
            "extracted_organisations": [],
            "social_profiles": [],
        },
    }
    entities = deep_public._entities_from_pages({"entities": []}, [page])
    types = {item["type"] for item in entities}
    assert "person" in types
    assert "email" in types
