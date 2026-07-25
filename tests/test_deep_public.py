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


def test_enrichment_adds_email_from_page_with_exact_phone(monkeypatch):
    page = {
        "id": "ev_page_1",
        "source": "deep_public_page",
        "source_url": "https://example.org/contact",
        "source_type": "public_page",
        "title": "Контакты",
        "excerpt": "Телефон +7 930 810-17-77, email owner@example.org",
        "reliability": 0.76,
        "direct_match": True,
        "content_hash": "page-hash",
        "metadata": {"extracted_emails": ["owner@example.org"]},
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
        "connector_runs": [],
        "summary": {"email": "не подтвержден"},
    }

    result = deep_public.enrich_case_with_public_pages(case)

    emails = [
        claim["value"]
        for entity in result["entities"]
        if entity["type"] == "email"
        for claim in entity["claims"]
    ]
    assert emails == ["owner@example.org"]
    assert result["summary"]["email"].startswith("кандидат:")
    assert result["summary"]["deep_public"]["pages_with_exact_phone"] == 1
