from pathlib import Path

from .deep_public import enrich_case_with_public_pages
from .identity_core import enrich_phone_case
from .jobs import append_log, finish_job, jobs
from .pipeline import mask_sensitive, run_pipeline_sync
from .report_renderer import render_report


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

        append_log(job_id, "[1/6] Нормализация и базовые источники...")
        case = run_pipeline_sync(phone, job_id)

        append_log(
            job_id,
            "[2/6] Identity Core: расширенные варианты номера и дополнительные "
            "поисковые запросы...",
        )
        case = enrich_phone_case(case, context)

        append_log(
            job_id,
            "[3/6] Глубокая проверка найденных публичных страниц...",
        )
        case = enrich_case_with_public_pages(case)
        deep_stats = case.get("summary", {}).get("deep_public", {})
        append_log(
            job_id,
            "Точные страницы: "
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
            "[4/6] Сведение сущностей и удаление технического шума...",
        )
        useful = deep_stats.get("useful_entities", 0)
        if useful:
            append_log(job_id, f"Полезных связанных сущностей найдено: {useful}.")
        else:
            append_log(
                job_id,
                "Полезных сущностей с прямым публичным подтверждением пока не найдено.",
            )

        append_log(job_id, "[5/6] Формирование result-first отчёта...")
        render_report(case, case_dir)

        append_log(job_id, "[6/6] Итоговый отчёт сформирован.")
        append_log(job_id, f"ФИО: {case['summary']['fio']}")
        append_log(job_id, f"Email: {case['summary']['email']}")
        finish_job(job_id)
    except Exception as exc:
        append_log(job_id, f"[FATAL] {mask_sensitive(str(exc))}")
        finish_job(job_id, "error")
