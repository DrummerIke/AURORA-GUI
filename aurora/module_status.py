from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModuleStatus:
    name: str
    category: str
    installed: bool
    command: str | None = None
    note: str = ""


def _binary(name: str, category: str, note: str = "") -> ModuleStatus:
    path = shutil.which(name)
    return ModuleStatus(name=name, category=category, installed=bool(path), command=path, note=note)


def _python(package: str, name: str, category: str, note: str = "") -> ModuleStatus:
    installed = importlib.util.find_spec(package) is not None
    return ModuleStatus(name=name, category=category, installed=installed, command=package if installed else None, note=note)


def get_module_status() -> list[dict]:
    modules = [
        _python("phonenumbers", "Phone metadata", "phone", "Нормализация, оператор и регион"),
        _python("ddgs", "Web search", "search", "Адресный поиск открытых публикаций"),
        _binary("phoneinfoga", "phone", "Дополнительное исследование номера"),
        _binary("sherlock", "username", "Быстрый поиск публичных профилей"),
        _binary("maigret", "username", "Расширенный поиск username"),
        _binary("socialscan", "username", "Проверка username и email на популярных платформах"),
        _binary("holehe", "email", "Публичные признаки использования email"),
        _binary("ghunt", "email", "Открытые данные экосистемы Google; требует отдельной настройки"),
        _binary("spiderfoot", "orchestrator", "Дополнительный OSINT-оркестратор"),
    ]
    return [asdict(module) for module in modules]
