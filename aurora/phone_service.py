from pathlib import Path

from phone_engine import create_report as create_phone_report
from web_search_engine import search_phone

from .jobs import append_log, finish_job, jobs


def phone_worker(job_id: str, phone: str) -> None:
    case_dir = Path(jobs[job_id]["dir"])
    try:
        append_log(job_id, "AURORA Phone Intelligence")
        append_log(job_id, f"Номер: {phone}")
        append_log(job_id, "[1/3] Нормализация номера...")
        report = create_phone_report(phone, case_dir)
        append_log(job_id, f"Оператор: {report['phone']['carrier'] or 'не определён'}")
        append_log(job_id, f"Регион: {report['phone']['location'] or report['phone']['region'] or 'не определён'}")
        append_log(job_id, "[2/3] Поиск и проверка открытых страниц...")
        result = search_phone(
            phone=report["phone"]["e164"],
            variants=report["variants"],
            output_dir=case_dir,
            max_results_per_query=8,
        )
        append_log(job_id, f"Сырых страниц: {result['raw_result_count']}")
        append_log(job_id, f"Полезных страниц: {result['result_count']}")
        append_log(job_id, f"Подтверждаемых находок: {result['finding_count']}")
        append_log(job_id, f"Отброшено мусора: {result['rejected_count']}")
        append_log(job_id, "[3/3] Готово. Открой findings.html или findings.txt.")
        finish_job(job_id)
    except Exception as exc:
        append_log(job_id, f"[FATAL] {exc}")
        finish_job(job_id, "error")
