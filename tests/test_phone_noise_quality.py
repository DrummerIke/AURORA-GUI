from aurora import result_quality


def test_reverse_phone_catalog_is_low_signal():
    assert result_quality.is_low_signal(
        "https://kto-zvonil-mne.ru/phone/9308101777",
        "Кто звонил с +79308101777",
        "Отзывы, оператор и регион номера",
    )
    assert result_quality.is_low_signal(
        "https://secab.ru/audit/79308101777",
        "+79308101777 чей звонок",
        "мошенники и проверка номера",
    )


def test_filter_removes_low_signal_evidence_and_orphan_candidate():
    case = {
        "evidence": [
            {
                "id": "ev_low",
                "source_url": "https://kto-zvonil-mne.ru/phone/9308101777",
                "source_type": "public_page",
                "title": "Кто звонил",
                "excerpt": "Андрей Иванов +79308101777",
                "direct_match": True,
            }
        ],
        "entities": [
            {
                "id": "entity_input",
                "type": "phone",
                "claims": [
                    {
                        "field": "phone",
                        "value": "+79308101777",
                        "evidence_ids": [],
                        "extraction_method": "input_normalizer",
                    }
                ],
            },
            {
                "id": "person_false",
                "type": "person",
                "claims": [
                    {
                        "field": "fio_candidate",
                        "value": "Андрей Иванов",
                        "evidence_ids": ["ev_low"],
                        "extraction_method": "phone_linked_public_page_name",
                    }
                ],
            },
        ],
        "summary": {"fio": "кандидат: Андрей Иванов (58%)", "email": "не подтвержден"},
    }

    result = result_quality.filter_low_value_results(case)

    assert result["evidence"] == []
    assert [entity["type"] for entity in result["entities"]] == ["phone"]
    assert result["summary"]["useful_entity_count"] == 0
    assert result["summary"]["quality_filter"]["suppressed_low_signal_evidence"] == 1


def test_high_signal_evidence_survives_filter():
    case = {
        "evidence": [
            {
                "id": "ev_high",
                "source_url": "https://vk.com/example",
                "source_type": "public_page",
                "title": "Иван Петров",
                "excerpt": "Контакт +79308101777",
                "direct_match": True,
            }
        ],
        "entities": [
            {
                "id": "person_real",
                "type": "person",
                "claims": [
                    {
                        "field": "fio_candidate",
                        "value": "Иван Петров",
                        "evidence_ids": ["ev_high"],
                        "extraction_method": "phone_linked_public_page_name",
                    }
                ],
            }
        ],
        "summary": {"fio": "кандидат: Иван Петров (68%)", "email": "не подтвержден"},
    }

    result = result_quality.filter_low_value_results(case)

    assert len(result["evidence"]) == 1
    assert result["entities"][0]["type"] == "person"
    assert result["summary"]["useful_entity_count"] == 1
