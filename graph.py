import os
import re
import time
import tempfile
import threading
import logging
import concurrent.futures
import requests
from typing import TypedDict
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from projects import (
    project_path, append_to_log, read_log,
    write_project_file, read_project_file, list_src_files, load_prompt
)

logger = logging.getLogger("ai-orchestrator.graph")

# ==========================================
# Mattermost config
# ==========================================
MATTERMOST_URL = os.environ.get("MATTERMOST_URL", "http://127.0.0.1:8065")
MATTERMOST_TEAM_NAME = os.environ.get("MATTERMOST_TEAM_NAME", "ai-engineering-factory")

AGENT_CHANNELS = {
    "researcher": "ai-researcher",
    "programmer": "ai-programmer",
    "debugger": "ai-debugger",
    "validator": "ai-validator",
    "reporter": "ai-reporter",
    "control": "ai-control",
}

_channel_cache: dict[str, str] = {}
_channel_cache_lock = threading.Lock()
_MM_MAX_LENGTH = 16383


def _truncate_message(message: str, max_len: int = _MM_MAX_LENGTH) -> str:
    if len(message) <= max_len:
        return message
    cutoff = message.rfind("\n", 0, max_len - 20)
    if cutoff < max_len // 2:
        cutoff = max_len - 20
    return message[:cutoff] + f"\n\n*... (truncated, {len(message)} total chars)*"


def _resolve_channel_id(channel_name: str) -> str | None:
    with _channel_cache_lock:
        if channel_name in _channel_cache:
            return _channel_cache[channel_name]
    bot_token = os.environ.get("MATTERMOST_BOT_TOKEN")
    if not bot_token:
        return None
    try:
        url = f"{MATTERMOST_URL}/api/v4/channels/name/{MATTERMOST_TEAM_NAME}/{channel_name}"
        resp = requests.get(url, headers={"Authorization": f"Bearer {bot_token}"}, timeout=10)
        resp.raise_for_status()
        cid = resp.json().get("id")
        if cid:
            with _channel_cache_lock:
                _channel_cache[channel_name] = cid
            return cid
    except Exception as e:
        logger.warning("Failed to resolve channel '%s': %s", channel_name, e)
    return None


def _post_to_channel(channel_id: str, message: str, root_id: str | None = None):
    bot_token = os.environ.get("MATTERMOST_BOT_TOKEN")
    if not bot_token:
        return
    payload = {"channel_id": channel_id, "message": _truncate_message(message)}
    if root_id:
        payload["root_id"] = root_id
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{MATTERMOST_URL}/api/v4/posts",
                headers={"Authorization": f"Bearer {bot_token}"},
                json=payload, timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_exc = e
            if attempt < 2:
                time.sleep(1.5 ** attempt)
    logger.error("_post_to_channel failed after 3 retries: %s", last_exc)
    return None


def post_agent_message(state: GraphState, agent_key: str, message: str):
    channel_name = AGENT_CHANNELS.get(agent_key)
    if not channel_name:
        return
    channel_id = _resolve_channel_id(channel_name)
    if channel_id:
        result = _post_to_channel(channel_id, message)
        if result is not None:
            return
    fallback_msg = f"[{agent_key}]\n{message[:500]}"
    try:
        _post_to_channel(state["channel_id"], fallback_msg, state.get("root_id"))
    except Exception:
        pass


def post_handoff(state: GraphState, from_agent: str, to_agent: str, summary: str):
    target_channel = AGENT_CHANNELS.get(to_agent)
    if not target_channel:
        return
    channel_id = _resolve_channel_id(target_channel)
    if not channel_id:
        return
    labels = {
        "researcher": "Researcher", "programmer": "Programmer",
        "debugger": "Debugger", "validator": "Validator", "reporter": "Reporter",
    }
    message = (
        f"**@{labels.get(to_agent, to_agent)}** — от {labels.get(from_agent, from_agent)}\n\n"
        f"{summary}\n\n*Проект: `{state['project_name']}`*"
    )
    _post_to_channel(channel_id, message)


def notify_mm(state: GraphState, message: str):
    bot_token = os.environ.get("MATTERMOST_BOT_TOKEN")
    if not bot_token:
        return
    headers = {"Authorization": f"Bearer {bot_token}"}
    payload = {
        "channel_id": state["channel_id"],
        "message": _truncate_message(message),
        "root_id": state["root_id"]
    }
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{MATTERMOST_URL}/api/v4/posts",
                headers=headers, json=payload, timeout=10
            )
            resp.raise_for_status()
            return
        except requests.RequestException as e:
            last_exc = e
            if attempt < 2:
                time.sleep(1.5 ** attempt)
    logger.error("notify_mm failed after 3 retries: %s", last_exc)


# ==========================================
# Per-agent LLM config from .env
# ==========================================
PROVIDER_BASE_URLS = {
    "zai": "https://api.z.ai/api/coding/paas/v4",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
}

_llm_cache: dict[str, object] = {}


def _create_llm(agent_key: str):
    """Создаёт ChatOpenAI для агента на основе .env конфигурации.
    
    .env format:
      PROGRAMMER_MODEL=glm-5.2
      PROGRAMMER_PROVIDER=zai
      PROGRAMMER_API_KEY=<key>
      PROGRAMMER_BASE_URL=<custom_url>
    Falls back to: {AGENT_KEY}_MODEL / DEFAULT_MODEL, etc.
    """
    upper = agent_key.upper()
    model = os.environ.get(f"{upper}_MODEL") or os.environ.get("DEFAULT_MODEL", "glm-5.2")
    provider = os.environ.get(f"{upper}_PROVIDER") or os.environ.get("DEFAULT_PROVIDER", "zai")
    api_key = os.environ.get(f"{upper}_API_KEY") or os.environ.get("DEFAULT_API_KEY") or os.environ.get("ZAI_API_KEY", "")
    base_url = os.environ.get(f"{upper}_BASE_URL") or PROVIDER_BASE_URLS.get(provider, PROVIDER_BASE_URLS["zai"])
    temperature = float(os.environ.get(f"{upper}_TEMPERATURE") or 0.0)

    if not api_key:
        raise RuntimeError(
            f"No API key for agent '{agent_key}'. Set {upper}_API_KEY or DEFAULT_API_KEY."
        )

    if agent_key in _llm_cache:
        return _llm_cache[agent_key]

    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=temperature)
    _llm_cache[agent_key] = llm
    return llm


# ==========================================
# ThreadPoolExecutor + timeout
# ==========================================
_llm_executor = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="llm")
LLM_CALL_TIMEOUT = 180


def llm_invoke(agent_key: str, messages: list, timeout: int = LLM_CALL_TIMEOUT):
    llm = _create_llm(agent_key)
    future = _llm_executor.submit(llm.invoke, messages)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"LLM call timed out after {timeout}s")
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {type(e).__name__}: {e}") from e


class DebugResult(BaseModel):
    has_errors: bool = Field(description="True if bugs found")
    error_description: str = Field(description="Error details")


def llm_invoke_structured(messages: list, timeout: int = LLM_CALL_TIMEOUT):
    llm = _create_llm("debugger")
    structured = llm.with_structured_output(DebugResult)
    future = _llm_executor.submit(structured.invoke, messages)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"LLM structured call timed out after {timeout}s")
    except Exception as e:
        raise RuntimeError(f"LLM structured call failed: {type(e).__name__}: {e}") from e


# ==========================================
# State
# ==========================================
class GraphState(TypedDict):
    channel_id: str
    root_id: str
    project_name: str
    user_id: str
    loop_count: int
    has_errors: bool


# ==========================================
# Error boundary
# ==========================================
def _safe_stage(state: GraphState, stage_name: str, fn):
    agent_key = {"1": "researcher", "2": "programmer", "3": "debugger",
                 "4": "validator", "5": "reporter"}.get(stage_name, "")
    try:
        return fn(state)
    except Exception as e:
        error_msg = f"[{stage_name}] FAILED: {type(e).__name__}: {e}"
        logger.exception(error_msg)
        if agent_key:
            post_agent_message(state, agent_key, f"**Error:**\n```\n{error_msg[:1000]}\n```")
        notify_mm(state, error_msg)
        append_to_log(state["project_name"], "error.md", error_msg)
        append_to_log(state["project_name"], "status.md", f"Stage {stage_name} Error: {e}")
        return {}


# ==========================================
# Stage 1: Researcher
# ==========================================
def stage_1_researcher(state: GraphState):
    post_agent_message(state, "researcher", "**AI Researcher** запущен.")
    notify_mm(state, "[Stage 1] Research — анализ задачи")

    plan = read_log(state["project_name"], "context.md")
    task = read_log(state["project_name"], "plan.md")

    system_prompt = load_prompt("researcher", state["project_name"])

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Задача:\n{task}\n\nПредыдущий контекст:\n{plan}")
    ]

    response = llm_invoke("researcher", messages)
    content = response.content.strip() if response and response.content else task

    append_to_log(state["project_name"], "context.md", content)
    append_to_log(state["project_name"], "status.md", "Stage 1 Complete")

    preview = content[:1000]
    post_agent_message(state, "researcher",
                       f"**Анализ завершён.**\n\n```\n{preview}\n```")

    post_handoff(state, "researcher", "programmer",
                 f"План проанализирован. Приступай к реализации.\n\n**Задача:**\n{task[:300]}")
    return {}


# ==========================================
# Stage 2: Programmer — генерирует файлы в src/
# ==========================================
def stage_2_programmer(state: GraphState):
    iteration = state["loop_count"] + 1
    post_agent_message(state, "programmer",
                       f"**AI Programmer** запущен (итерация {iteration}/3).")
    notify_mm(state, f"[Stage 2] Programmer — итерация {iteration}")

    plan = read_log(state["project_name"], "context.md")
    errors = read_log(state["project_name"], "error.md")

    system_prompt = load_prompt("programmer", state["project_name"])

    existing_files = list_src_files(state["project_name"])
    files_context = ""
    for f in existing_files:
        content = read_project_file(state["project_name"], f"src/{f}")
        files_context += f"\n--- {f} ---\n{content[:500]}\n"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=(
            f"Контекст:\n{plan}\n\n"
            f"Существующие файлы в проекте:{files_context}\n\n"
            f"Отчёт об ошибках:\n{errors}\n\n"
            f"Генерируй код. Выводи каждый файл в формате:\n"
            f"```filepath:src/main.py\n<code>\n```"
        ))
    ]

    response = llm_invoke("programmer", messages)
    content = response.content.strip() if response and response.content else "# Empty response"

    # Парсинг генерированных файлов из ответа LLM
    file_pattern = re.compile(r"```filepath:(\S+)\n(.*?)```", re.DOTALL)
    matches = file_pattern.findall(content)
    if matches:
        for filepath, code in matches:
            write_project_file(state["project_name"], filepath, code)
            post_agent_message(state, "programmer",
                               f"**Создан файл:** `{filepath}` ({len(code)} chars)")
        append_to_log(state["project_name"], "context.md",
                       f"Iteration {iteration}: generated {len(matches)} files:\n" +
                       "\n".join(f"  - {fp}" for fp, _ in matches))
    else:
        append_to_log(state["project_name"], "context.md",
                       f"Iteration {iteration}: no file markers found, saving as raw output")

    append_to_log(state["project_name"], "status.md", f"Stage 2 Complete (iteration {iteration})")

    post_agent_message(state, "programmer",
                       f"**Код написан** (итерация {iteration}, {len(matches)} файлов).")
    post_handoff(state, "programmer", "debugger",
                 f"Код готов к проверке (итерация {iteration}).")
    return {}


# ==========================================
# Stage 3: Debugger
# ==========================================
def stage_3_debugger(state: GraphState):
    post_agent_message(state, "debugger", "**AI Debugger** запущен.")
    notify_mm(state, "[Stage 3] Debug — проверка кода")

    existing_files = list_src_files(state["project_name"])
    code_context = ""
    for f in existing_files:
        content = read_project_file(state["project_name"], f"src/{f}")
        code_context += f"\n--- {f} ---\n{content[:3000]}\n"

    if not code_context.strip():
        post_agent_message(state, "debugger", "**Нет файлов для проверки.**")
        append_to_log(state["project_name"], "error.md", "Empty code — nothing to debug")
        return {"has_errors": False}

    plan = read_log(state["project_name"], "context.md")
    system_prompt = load_prompt("debugger", state["project_name"])

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"План:\n{plan}\n\nФайлы проекта:{code_context}")
    ]

    result = llm_invoke_structured(messages)

    if result.has_errors and not result.error_description.strip():
        result.error_description = "Errors found (no details)"

    if result.has_errors:
        write_project_file(state["project_name"], "src/errors.md", result.error_description)
        append_to_log(state["project_name"], "error.md", result.error_description)

        post_agent_message(state, "debugger",
                           f"**Найдены ошибки.**\n```\n{result.error_description[:1000]}\n```")

        post_handoff(state, "debugger", "programmer",
                     f"В коде ошибки (попытка {state['loop_count'] + 1}/3).\n"
                     f"Смотри `src/errors.md`")

        return {
            "has_errors": True,
            "loop_count": state["loop_count"] + 1
        }
    else:
        append_to_log(state["project_name"], "error.md", "Code is clean")

        post_agent_message(state, "debugger",
                           "**Код чист.** Ошибок не обнаружено.")

        post_handoff(state, "debugger", "validator",
                     "Код прошёл отладку. Проверь соответствие требованиям.")
        return {"has_errors": False}


# ==========================================
# Stage 4: Validator
# ==========================================
def stage_4_validator(state: GraphState):
    post_agent_message(state, "validator", "**AI Validator** запущен.")
    notify_mm(state, "[Stage 4] Validator — финальная сверка")

    plan = read_log(state["project_name"], "plan.md")
    context = read_log(state["project_name"], "context.md")

    existing_files = list_src_files(state["project_name"])
    code_context = ""
    for f in existing_files:
        content = read_project_file(state["project_name"], f"src/{f}")
        code_context += f"\n--- {f} ---\n{content[:3000]}\n"

    if not code_context.strip():
        post_agent_message(state, "validator", "**Нет кода для валидации.**")
        append_to_log(state["project_name"], "status.md", "Stage 4 Skipped")
        return {}

    system_prompt = load_prompt("validator", state["project_name"])

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"План:\n{plan}\n\nКонтекст:\n{context}\n\nФайлы:{code_context}")
    ]

    response = llm_invoke("validator", messages)
    verdict = response.content.strip() if response and response.content else "No verdict"

    append_to_log(state["project_name"], "status.md", f"Stage 4 Complete — {verdict[:200]}")

    post_agent_message(state, "validator",
                       f"**Валидация завершена.**\n```\n{verdict[:800]}\n```")

    post_handoff(state, "validator", "reporter",
                 "Валидация пройдена.")
    return {}


# ==========================================
# Stage 5: Reporter
# ==========================================
def stage_5_final(state: GraphState):
    post_agent_message(state, "reporter", "**AI Reporter** формирует отчёт.")

    src_files = list_src_files(state["project_name"])
    files_summary = "\n".join(f"- `{f}`" for f in src_files) if src_files else "(no files)"
    status = read_log(state["project_name"], "status.md")
    loop_count = state["loop_count"]

    report = (
        f"**Final Report**\n\n"
        f"Project: `{state['project_name']}`\n"
        f"Debug iterations: {loop_count}/3\n\n"
        f"Generated files:\n{files_summary}\n\n"
        f"Status log:\n```\n{status[-1000:]}\n```"
    )
    post_agent_message(state, "reporter", report)

    notify_mm(state,
              f"**Pipeline Complete** ({loop_count} debug iterations)\n\n"
              f"Project: `{state['project_name']}`\n"
              f"Files: {files_summary}\n\n"
              f"---\n"
              f"*Agent channels: ~ai-researcher | ~ai-programmer | ~ai-debugger | ~ai-validator | ~ai-reporter*")
    return {}


# ==========================================
# Router
# ==========================================
def route_after_debug(state: GraphState) -> str:
    try:
        if state["has_errors"]:
            if state["loop_count"] >= 3:
                post_agent_message(state, "control",
                                   "**Guardrail** Loop limit 3/3 reached. Forcing validation.")
                notify_mm(state, "[Guardrail] Loop limit 3/3 — forcing validation.")
                return "stage_4_validator"

            post_agent_message(state, "control",
                               f"**Loop** iteration {state['loop_count']}/3 — returning to Programmer.")
            notify_mm(state, f"[Loop] Errors found — returning to Stage 2 ({state['loop_count']}/3)")
            return "stage_2_programmer"

        return "stage_4_validator"
    except Exception as e:
        logger.exception("route_after_debug crashed: %s", e)
        return "stage_4_validator"


# ==========================================
# Graph compilation
# ==========================================
workflow = StateGraph(GraphState)

workflow.add_node("stage_1_researcher", lambda s: _safe_stage(s, "1", stage_1_researcher))
workflow.add_node("stage_2_programmer", lambda s: _safe_stage(s, "2", stage_2_programmer))
workflow.add_node("stage_3_debugger", lambda s: _safe_stage(s, "3", stage_3_debugger))
workflow.add_node("stage_4_validator", lambda s: _safe_stage(s, "4", stage_4_validator))
workflow.add_node("stage_5_final", lambda s: _safe_stage(s, "5", stage_5_final))

workflow.add_edge("stage_1_researcher", "stage_2_programmer")
workflow.add_edge("stage_2_programmer", "stage_3_debugger")

workflow.add_conditional_edges(
    "stage_3_debugger", route_after_debug,
    {"stage_2_programmer": "stage_2_programmer", "stage_4_validator": "stage_4_validator"}
)

workflow.add_edge("stage_4_validator", "stage_5_final")
workflow.add_edge("stage_5_final", END)

workflow_compiled = workflow.compile()

# ==========================================
# Entry point
# ==========================================
_running_workspaces: set[str] = set()


def run_agentic_workflow(
    channel_id: str, root_id: str, project_name: str,
    user_id: str, initial_task: str = ""
):
    key = f"{project_name}:{root_id}"
    if key in _running_workspaces:
        logger.warning("Duplicate workflow %s — ignored", key)
        return

    _running_workspaces.add(key)
    dummy_state = GraphState(
        channel_id=channel_id, root_id=root_id,
        project_name=project_name, user_id=user_id,
        loop_count=0, has_errors=False
    )

    try:
        if initial_task.strip():
            append_to_log(project_name, "plan.md", initial_task)

        initial_state = GraphState(
            channel_id=channel_id, root_id=root_id,
            project_name=project_name, user_id=user_id,
            loop_count=0, has_errors=False
        )
        workflow_compiled.invoke(initial_state)
    except Exception as e:
        error_msg = f"[CRITICAL] {type(e).__name__}: {e}"
        logger.exception(error_msg)
        try:
            notify_mm(dummy_state, error_msg)
        except Exception:
            pass
        append_to_log(project_name, "error.md", error_msg)
    finally:
        _running_workspaces.discard(key)
