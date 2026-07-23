from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModuleStatus:
    name: str
    category: str
    state: str
    command: str | None = None
    note: str = ""
    version: str = ""

    @property
    def installed(self) -> bool:
        return self.state in {"ready", "limited", "configuration_required"}


def _is_android_prroot() -> bool:
    text = " ".join(
        [
            platform.platform(),
            platform.release(),
            os.getenv("PREFIX", ""),
            os.getenv("ANDROID_ROOT", ""),
            os.getenv("PROOT_TMP_DIR", ""),
        ]
    ).lower()
    return "android" in text or "termux" in text or "proot" in text


def _version(path: str, args: list[str] | None = None) -> str:
    commands = [args or ["--version"], ["-version"], ["version"], ["-V"]]
    for command_args in commands:
        try:
            result = subprocess.run(
                [path, *command_args],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
            if output:
                return output.splitlines()[0][:100]
        except Exception:
            continue
    return ""


def _binary(
    name: str,
    category: str,
    note: str = "",
    *,
    limited_on_prroot: bool = False,
    configuration_required: bool = False,
) -> ModuleStatus:
    path = shutil.which(name)
    if not path:
        if name == "phoneinfoga":
            return ModuleStatus(
                name=name,
                category=category,
                state="upstream_broken",
                note="Сборка upstream требует отсутствующий web/client/dist; модуль временно исключён из обязательных.",
            )
        return ModuleStatus(name=name, category=category, state="missing", note=note)

    state = "ready"
    effective_note = note
    if limited_on_prroot and _is_android_prroot():
        state = "limited"
        effective_note = "Установлен, но raw-socket функции ограничены Android/PRoot; используйте VPS или обычный Linux."
    elif configuration_required:
        state = "configuration_required"

    return ModuleStatus(
        name=name,
        category=category,
        state=state,
        command=path,
        note=effective_note,
        version=_version(path),
    )


def _python(package: str, name: str, category: str, note: str = "") -> ModuleStatus:
    installed = importlib.util.find_spec(package) is not None
    return ModuleStatus(
        name=name,
        category=category,
        state="ready" if installed else "missing",
        command=package if installed else None,
        note=note,
    )


def get_module_status() -> list[dict]:
    modules = [
        _python("phonenumbers", "Phone metadata", "core", "Нормализация, оператор и регион"),
        _python("ddgs", "Web search", "core", "Поиск открытых публикаций"),
        _binary("phoneinfoga", "phone", "Дополнительное исследование номера"),
        _binary("sherlock", "identity", "Быстрый поиск публичных профилей"),
        _binary("maigret", "identity", "Расширенный поиск username"),
        _binary("socialscan", "identity", "Проверка username и email"),
        _binary("holehe", "identity", "Публичные признаки использования email"),
        _binary("ghunt", "identity", "Данные экосистемы Google", configuration_required=True),
        _binary("spiderfoot", "orchestrator", "OSINT-оркестратор"),
        _binary("dnsx", "infrastructure", "DNS-разведка"),
        _binary("subfinder", "infrastructure", "Поиск поддоменов"),
        _binary("httpx", "infrastructure", "Проверка доступности веб-узлов"),
        _binary("katana", "infrastructure", "Веб-краулер"),
        _binary("naabu", "infrastructure", "Сканирование портов", limited_on_prroot=True),
        _binary("nuclei", "security", "Проверка по шаблонам; только для разрешённых целей"),
        _binary("waybackurls", "archive", "Архивные URL"),
        _binary("gau", "archive", "URL из публичных архивов"),
        _binary("amass", "infrastructure", "Глубокая разведка доменов"),
        _binary("gitleaks", "secrets", "Поиск секретов в собственных репозиториях"),
        _binary("trufflehog", "secrets", "Поиск утечек секретов в разрешённых источниках"),
    ]
    return [{**asdict(module), "installed": module.installed} for module in modules]
