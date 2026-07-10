import os
import json
import logging
from datetime import datetime

logger = logging.getLogger("ai-orchestrator.projects")

PROJECTS_ROOT = "/var/lib/ai-workspace/projects"
DEFAULT_PROMPTS_DIR = "/opt/ai-orchestrator/default-prompts"

AGENT_NAMES = ["researcher", "programmer", "debugger", "validator", "reporter"]

# Встроенные промты — фоллбэк если нет файла ни в проекте, ни в default-prompts/
BUILTIN_PROMPTS = {
    "researcher": (
        "Ты опытный аналитик. Разбей задачу на подзадачи, "
        "определи требуемые технологии и архитектуру."
    ),
    "programmer": (
        "Ты Senior Developer. Твоя задача писать качественный код на основе плана."
    ),
    "debugger": (
        "Ты QA Engineer и Debugger. Проверь код на ошибки и соответствие плану."
    ),
    "validator": (
        "Ты финальный валидатор. Проверь код на соответствие требованиям."
    ),
}


def ensure_projects_root():
    os.makedirs(PROJECTS_ROOT, exist_ok=True)


def project_path(name: str) -> str:
    return os.path.join(PROJECTS_ROOT, name)


def project_src_path(name: str) -> str:
    return os.path.join(PROJECTS_ROOT, name, "src")


def project_prompts_path(name: str) -> str:
    return os.path.join(PROJECTS_ROOT, name, "prompts")


def project_exists(name: str) -> bool:
    return os.path.isdir(project_path(name))


def create_project(name: str) -> dict:
    if not name or not _safe_name(name):
        return {"ok": False, "error": "Invalid project name (only a-z, 0-9, _-)"}

    if project_exists(name):
        return {"ok": False, "error": f"Project '{name}' already exists"}

    pp = project_path(name)
    os.makedirs(os.path.join(pp, "src"), exist_ok=True)
    os.makedirs(os.path.join(pp, "prompts"), exist_ok=True)

    for filename in ["context.md", "error.md", "status.md", "history.md"]:
        filepath = os.path.join(pp, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# {filename}\nCreated: {datetime.now().isoformat()}\n")

    with open(os.path.join(pp, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "created": datetime.now().isoformat()}, f, indent=2)

    return {"ok": True, "project": name, "path": pp}


def list_projects() -> list[dict]:
    ensure_projects_root()
    result = []
    if not os.path.isdir(PROJECTS_ROOT):
        return result
    for entry in sorted(os.listdir(PROJECTS_ROOT)):
        pp = os.path.join(PROJECTS_ROOT, entry)
        if os.path.isdir(pp) and os.path.exists(os.path.join(pp, "meta.json")):
            meta = {}
            try:
                with open(os.path.join(pp, "meta.json"), "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                pass
            result.append({"name": entry, "created": meta.get("created", "unknown")})
    return result


def get_active_project(user_id: str) -> str | None:
    filepath = os.path.join(PROJECTS_ROOT, ".active")
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            mapping = json.load(f)
        return mapping.get(user_id)
    except Exception:
        return None


def set_active_project(user_id: str, name: str) -> dict:
    if not project_exists(name):
        return {"ok": False, "error": f"Project '{name}' not found"}

    filepath = os.path.join(PROJECTS_ROOT, ".active")
    mapping = {}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                mapping = json.load(f)
        except Exception:
            pass

    mapping[user_id] = name
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)

    return {"ok": True, "project": name}


def append_to_log(project_name: str, filename: str, content: str):
    """Append-only запись в сервисный .md файл с timestamp."""
    filepath = os.path.join(project_path(project_name), filename)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n---\n## [{timestamp}]\n\n{content}\n"
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(entry)


def read_log(project_name: str, filename: str) -> str:
    filepath = os.path.join(project_path(project_name), filename)
    if not os.path.exists(filepath):
        return ""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def write_project_file(project_name: str, rel_path: str, content: str):
    """Запись файла в папку проекта (используется для src/*.py и т.д.)"""
    full_path = os.path.join(project_path(project_name), rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)


def read_project_file(project_name: str, rel_path: str) -> str:
    full_path = os.path.join(project_path(project_name), rel_path)
    if not os.path.exists(full_path):
        return ""
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


def list_src_files(project_name: str) -> list[str]:
    """Возвращает список файлов в src/ папке проекта."""
    src = project_src_path(project_name)
    if not os.path.isdir(src):
        return []
    result = []
    for root, dirs, files in os.walk(src):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), src)
            result.append(rel)
    return sorted(result)


def load_prompt(agent_key: str, project_name: str | None = None) -> str:
    """Загрузка промта для агента. Приоритет:
    1. project/prompts/{agent}-prompt.md
    2. /opt/ai-orchestrator/default-prompts/{agent}-prompt.md
    3. BUILTIN_PROMPTS[agent_key]
    """
    # 1. Project-specific
    if project_name:
        pp = os.path.join(project_prompts_path(project_name), f"{agent_key}-prompt.md")
        if os.path.exists(pp):
            with open(pp, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return content

    # 2. Global default
    gp = os.path.join(DEFAULT_PROMPTS_DIR, f"{agent_key}-prompt.md")
    if os.path.exists(gp):
        with open(gp, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            return content

    # 3. Builtin fallback
    return BUILTIN_PROMPTS.get(agent_key, "")


def _safe_name(name: str) -> bool:
    import re
    return bool(re.match(r"^[a-zA-Z0-9_\-]+$", name))
