from aurora import deep_public


def test_phone_present_accepts_russian_local_and_e164_formats():
    phone = "+79308101777"
    assert deep_public.phone_present("+7 (930) 810-17-77", phone)
    assert deep_public.phone_present("8 930 810 17 77", phone)


def test_clean_page_removes_scripts_and_keeps_visible_text():
    title, text = deep_public.clean_page(
        "<html><head><title>Контакты</title><script>secret()</script></head>"
        "<body><p>Телефон +7 930 810-17-77</p></body></html>"
    )
    assert title == "Контакты"
    assert "secret" not in text
    assert "+7 930 810-17-77" in text


def test_safe_public_url_rejects_local_targets():
    assert not deep_public.safe_public_url("http://127.0.0.1/admin")
    assert not deep_public.safe_public_url("http://localhost:8080")
    assert not deep_public.safe_public_url("file:///etc/passwd")


def test_extracts_names_organisations_and_social_profiles():
    text = (
        "Контактное лицо: Иван Петров. "
        "Компания ООО «Альфа Трейд». Телефон +7 930 810-17-77"
    )
    names = deep_public._extract_names(text)
    organisations = deep_public._extract_orgs(text)
    profiles = deep_public._extract_social_profiles(
        '<a href="https://t.me/ivan_petrov">Telegram</a>',
        "https://example.org/contact",
    )

    assert "Иван Петров" in names
    assert any("Альфа Трейд" in item for item in organisations)
    assert profiles == [
        {
            "network": "telegram",
            "username": "ivan_petrov",
            "url": "https://t.me/ivan_petrov",
        }
    ]


def test_enrichment_adds_multiple_useful_entities_from_exact_phone_page(monkeypatch):
    page = {
        "id": "ev_page_1",
        "source": "deep_public_page",
        "source_url": "https://example.org/contact",
        "source_type": "public_page",
        "title": "Контакты",
        "excerpt": (
            "Контактное лицо: Иван Петров. Телефон +7 930 810-17-77, "
            "email owner@example.org, ООО «Альфа Трейд»."
        ),
        "reliability": 0.76,
        "direct_match": True,
        "content_hash": "page-hash",
        "metadata": {
            "extracted_emails": ["owner@example.org"],
            "extracted_names": ["Иван Петров"],
            "extracted_organisations": ["ООО «Альфа Трейд»"],
            "social_profiles": [
                {
                    "network": "telegram",
                    "username": "ivan_petrov",
                    "url": "https://t.me/ivan_petrov",
                }
            ],
        },
    }
    monkeypatch.setattr(
        deep_public,
        "fetch_phone_linked_pages",
        lambda evidence, phone: [page],
    )
    case = {
        "input": {
            "type": "phone",
            "raw": "+79308101777",
            "normalized": "+79308101777",
        },
        "evidence": [],
        "entities": [],
        "relationships": [],
        "connector_runs": [],
        "summary": {"fio": "не подтверждено", "email": "не подтвержден"},
    }

    result = deep_public.enrich_case_with_public_pages(case)
    types = {entity["type"] for entity in result["entities"]}

    assert {"person", "email", "organization", "username"}.issubset(types)
    assert result["summary"]["fio"].startswith("кандидат:")
    assert result["summary"]["email"].startswith("кандидат:")
    assert result["summary"]["deep_public"]["pages_with_exact_phone"] == 1
    assert result["summary"]["deep_public"]["useful_entities"] == 4
    assert len(result["relationships"]) == 4


def test_empty_enrichment_does_not_invent_identity(monkeypatch):
    monkeypatch.setattr(
        deep_public,
        "fetch_phone_linked_pages",
        lambda evidence, phone: [],
    )
    case = {
        "input": {
            "type": "phone",
            "raw": "+79308101777",
            "normalized": "+79308101777",
        },
        "evidence": [],
        "entities": [],
        "connector_runs": [],
        "summary": {"fio": "не подтверждено", "email": "не подтвержден"},
    }

    result = deep_public.enrich_case_with_public_pages(case)

    assert result["summary"]["deep_public"]["useful_entities"] == 0
    assert result["summary"]["fio"] == "не подтверждено"
