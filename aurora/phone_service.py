from pathlib import Path

from phone_engine import create_report as create_phone_report
from web_search_engine import search_phone

from .enrichment import enrich_findings
from .jobs import append_log, finish_job, jobs
from .person_card import build_person_card


def phone_worker(job_id: str, phone: str) -> None:
    case_dir = Path(jobs[job_id]["dir"])
    try:
        append_log(job_id, "AURORA Phone Intelligence")
        append_log(job_id, f"Номер: {phone}")
        append_log(job_id, "[1/4] Анализ номера и региона...")

        report = create_phone_report(phone, case_dir)
        phone_data = report.get("phone", {})
        append_log(job_id, f"Оператор: {phone_data.get('carrier') or 'не определён'}")
        append_log(job_id, f"Регион: {phone_data.get('location') or phone_data.get('region') or 'не определён'}")

        append_log(job_id, "[2/4] Быстрый сбор открытых данных...")
        result = search_phone(
            phone=phone_data["e164"],
            variants=report["variants"],
            output_dir=case_dir,
            max_results_per_query=6,
        )

        findings = result.get("findings", [])
        append_log(job_id, f"Первичных сущностей: {len(findings)}")

        append_log(job_id, "[3/4] Каскадное обогащение email и username...")
        enrichment = enrich_findings(findings, case_dir)
        module_count = len(enrichment.get("modules", []))
        profile_count = len(enrichment.get("profiles", []))
        append_log(job_id, f"Запущено модулей: {module_count}")
        append_log(job_id, f"Дополнительных профилей: {profile_count}")

        card = build_person_card(report, result, case_dir, enrichment=enrichment)

        append_log(job_id, "[4/4] Карточка сформирована.")
        if card.get("possible_name"):
            append_log(
                job_id,
                f"Вероятное ФИО: {card['possible_name']} "
                f"({card.get('name_confidence', 0)}%)",
            )
        else:
            append_log(job_id, "ФИО в открытых источниках не подтверждено.")

        entity_count = sum(len(items) for items in card.get("entities", {}).values())
        append_log(job_id, f"Всего связанных сущностей: {entity_count}")
        append_log(job_id, "Открой «Карточку человека».")
        finish_job(job_id)

    except Exception as exc:
        append_log(job_id, f"[FATAL] {exc}")
        finish_job(job_id, "error")
