from pathlib import Path

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
            append_log(job_id, "Известный контекст добавлен пользователем; он будет проверяться, а не считаться доказанным.")
        append_log(job_id, "[1/5] Нормализация и планирование источников...")
        append_log(job_id, "[2/5] Параллельный сбор с таймаутами и изоляцией ошибок...")
        case = run_pipeline_sync(phone, job_id)
        append_log(job_id, "[3/5] Identity Core: дополнительные форматы номера, контекстные запросы и очистка SEO-мусора...")
        case = enrich_phone_case(case, context)
        append_log(job_id, "[4/5] Разрешение сущностей, дедупликация и оценка уверенности...")
        render_report(case, case_dir)
        append_log(job_id, "[5/5] Итоговый отчет сформирован.")
        append_log(job_id, f"ФИО: {case['summary']['fio']}")
        append_log(job_id, f"Email: {case['summary']['email']}")
        finish_job(job_id)
    except Exception as exc:
        append_log(job_id, f"[FATAL] {mask_sensitive(str(exc))}")
        finish_job(job_id, "error")
