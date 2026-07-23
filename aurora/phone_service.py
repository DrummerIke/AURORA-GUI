from pathlib import Path
from .jobs import append_log, finish_job, jobs
from .pipeline import run_pipeline_sync, mask_sensitive
from .report_renderer import render_report

def phone_worker(job_id: str, phone: str) -> None:
    case_dir = Path(jobs[job_id]["dir"])
    try:
        append_log(job_id, "AURORA законный OSINT-конвейер")
        append_log(job_id, f"Запрос: {mask_sensitive(phone)}")
        append_log(job_id, "[1/4] Нормализация и планирование источников...")
        append_log(job_id, "[2/4] Параллельный сбор с таймаутами и изоляцией ошибок...")
        case = run_pipeline_sync(phone, job_id)
        append_log(job_id, "[3/4] Извлечение, фильтрация мусора, дедупликация и оценка уверенности...")
        render_report(case, case_dir)
        append_log(job_id, "[4/4] Итоговый отчет сформирован.")
        append_log(job_id, f"ФИО: {case['summary']['fio']}")
        append_log(job_id, f"Email: {case['summary']['email']}")
        finish_job(job_id)
    except Exception as exc:
        append_log(job_id, f"[FATAL] {mask_sensitive(str(exc))}")
        finish_job(job_id, "error")
