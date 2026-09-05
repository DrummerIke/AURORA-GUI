from pathlib import Path

from .deep_public import enrich_case_with_public_pages
from .identity_core import enrich_phone_case
from .jobs import append_log, finish_job, jobs
from .pipeline import mask_sensitive, run_pipeline_sync
from .report_renderer import render_report
from .result_quality import enrich_targeted_search, filter_low_value_results


def phone_worker(job_id: str, phone: str, context: dict | None = None) -> None:
    case_dir = Path(jobs[job_id]["dir"])
    context = context or {}
    try:
        append_log(job_id, "AURORA законный OSINT-конвейер")
        append_log(job_id, f"Запрос: {mask_sensitive(phone)}")
        if context:
            append_log(
                job_id,
                "Известный контекст добавлен пользователем; он будет проверяться, "
                "а не считаться доказанным.",
            )

        append_log(job_id, "[1/7] Нормализация и базовые источники...")
        case = run_pipeline_sync(phone, job_id)

        append_log(
            job_id,
            "[2/7] Прицельный поиск по социальным сетям, объявлениям, "
            "бизнес-источникам и публичным документам...",
        )
        case = enrich_targeted_search(case)
        targeted = case.get("summary", {}).get("targeted_search", {})
        append_log(
            job_id,
            "Прицельных результатов: "
            f"{targeted.get('results', 0)}; "
            "высокого сигнала: "
            f"{targeted.get('high_signal_results', 0)}.",
        )

        append_log(
            job_id,
            "[3/7] Identity Core: варианты номера, корреляция и первичная "
            "оценка кандидатов...",
        )
        case = enrich_phone_case(case, context)
        case = filter_low_value_results(case)

        append_log(
            job_id,
            "[4/7] Глубокая проверка только содержательных публичных страниц...",
        )
        case = enrich_case_with_public_pages(case)
        case = filter_low_value_results(case)
        deep_stats = case.get("summary", {}).get("deep_public", {})
        append_log(
            job_id,
            "Точные содержательные страницы: "
            f"{deep_stats.get('pages_with_exact_phone', 0)}; "
            "ФИО-кандидаты: "
            f"{deep_stats.get('person_candidates', 0)}; "
            "email: "
            f"{deep_stats.get('email_candidates', 0)}; "
            "организации: "
            f"{deep_stats.get('organization_candidates', 0)}; "
            "публичные профили: "
            f"{deep_stats.get('username_candidates', 0)}.",
        )

        append_log(
            job_id,
            "[5/7] Удаление каталогов «кто звонил», SEO-шаблонов и "
            "кандидатов без живого доказательства...",
        )
        quality = case.get("summary", {}).get("quality_filter", {})
        append_log(
            job_id,
            "Скрыто низкосигнальных доказательств: "
            f"{quality.get('suppressed_low_signal_evidence', 0)}; "
            "осиротевших кандидатов: "
            f"{quality.get('suppressed_orphan_entities', 0)}.",
        )

        append_log(job_id, "[6/7] Формирование result-first отчёта...")
        render_report(case, case_dir)

        append_log(job_id, "[7/7] Итоговый отчёт сформирован.")
        append_log(job_id, f"ФИО: {case['summary']['fio']}")
        append_log(job_id, f"Email: {case['summary']['email']}")
        append_log(
            job_id,
            "Полезных связанных сущностей: "
            f"{case.get('summary', {}).get('useful_entity_count', 0)}.",
        )
        finish_job(job_id)
    except Exception as exc:
        append_log(job_id, f"[FATAL] {mask_sensitive(str(exc))}")
        finish_job(job_id, "error")
