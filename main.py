import os
import re
import time
import signal
import logging
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from projects import (
    ensure_projects_root, create_project, list_projects,
    get_active_project, set_active_project
)
from graph import run_agentic_workflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ai-orchestrator")

ensure_projects_root()

app = FastAPI()

_shutting_down = False


def handle_sigterm(signum, frame):
    global _shutting_down
    _shutting_down = True
    logger.warning("SIGTERM/SIGINT received — initiating shutdown")
    os._exit(0)


signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)


class RateLimiter:
    def __init__(self, max_per_channel: int = 2, window_sec: float = 10.0):
        self.max_per_channel = max_per_channel
        self.window_sec = window_sec
        self._buckets: dict[str, list[float]] = {}

    def allow(self, channel_id: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_sec
        timestamps = self._buckets.setdefault(channel_id, [])
        timestamps[:] = [t for t in timestamps if t > window_start]
        if len(timestamps) >= self.max_per_channel:
            return False
        timestamps.append(now)
        return True


rate_limiter = RateLimiter()
_running_tasks: set[str] = set()
MAX_TEXT_LENGTH = 4000
ALLOWED_PATH_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


# ==========================================
# Slash-команды (/project)
# ==========================================
@app.post("/slash")
async def slash_command(request: Request):
    if _shutting_down:
        return {"text": "Server shutting down.", "response_type": "ephemeral"}

    form = await request.form()
    command = form.get("command", "").strip()
    text = form.get("text", "").strip()
    channel_id = form.get("channel_id", "")
    user_id = form.get("user_id", "")
    user_name = form.get("user_name", "unknown")

    if command != "/project":
        return {"text": f"Unknown command: {command}", "response_type": "ephemeral"}

    parts = text.split(maxsplit=2) if text else []
    action = parts[0] if parts else ""

    if action == "create":
        name = parts[1] if len(parts) > 1 else ""
        result = create_project(name)
        if result["ok"]:
            set_active_project(user_id, name)
            return {
                "response_type": "ephemeral",
                "text": f"Project **{name}** created and selected.\n"
                       f"Path: `{result['path']}`\n\n"
                       f"Place custom prompts in: `prompts/{{agent}}-prompt.md`\n"
                       f"Agents: researcher, programmer, debugger, validator, reporter"
            }
        return {"response_type": "ephemeral", "text": f"Error: {result['error']}"}

    elif action == "select":
        name = parts[1] if len(parts) > 1 else ""
        result = set_active_project(user_id, name)
        if result["ok"]:
            return {
                "response_type": "ephemeral",
                "text": f"Active project: **{name}**\n"
                       f"Use `ai_lead <task>` to start working."
            }
        return {"response_type": "ephemeral", "text": f"Error: {result['error']}"}

    elif action == "list":
        projects = list_projects()
        active = get_active_project(user_id)
        if not projects:
            return {"response_type": "ephemeral", "text": "No projects. Use `/project create <name>`."}
        lines = []
        for p in projects:
            marker = "** ← active**" if p["name"] == active else ""
            lines.append(f"- `{p['name']}` (created: {p.get('created', '?')}){marker}")
        return {"response_type": "ephemeral", "text": "Projects:\n\n" + "\n".join(lines)}

    else:
        return {
            "response_type": "ephemeral",
            "text": (
                "Usage:\n"
                "• `/project create <name>` — create and select\n"
                "• `/project select <name>` — switch project\n"
                "• `/project list` — show all projects"
            )
        }


# ==========================================
# Webhook: ai_lead <task>
# ==========================================
@app.post("/webhook")
async def mattermost_webhook(request: Request, background_tasks: BackgroundTasks):
    if _shutting_down:
        raise HTTPException(status_code=503, detail="Server shutting down")

    content_type = request.headers.get("content-type", "")
    try:
        if "application/json" in content_type:
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    if data.get("user_name", "").endswith("bot") or data.get("bot_id"):
        return {"status": "ignored"}

    channel_id = data.get("channel_id")
    post_id = data.get("post_id")
    user_text = data.get("text", "")
    user_id = data.get("user_id", "")

    if not channel_id or not post_id:
        raise HTTPException(status_code=400, detail="Missing channel_id or post_id")

    if not user_text.strip():
        return {"status": "ignored"}

    if len(user_text) > MAX_TEXT_LENGTH:
        user_text = user_text[:MAX_TEXT_LENGTH]

    if not rate_limiter.allow(channel_id):
        return {"status": "rate_limited"}

    if post_id in _running_tasks:
        return {"status": "already_running"}

    project_name = get_active_project(user_id) if user_id else None
    if not project_name:
        return {"status": "no_project"}

    if not ALLOWED_PATH_RE.match(str(post_id)):
        return {"status": "rejected", "reason": "unsafe post_id"}

    _running_tasks.add(post_id)

    background_tasks.add_task(
        _run_with_cleanup,
        post_id=post_id,
        channel_id=channel_id,
        user_id=user_id,
        project_name=project_name,
        user_text=user_text
    )

    return {"status": "received"}


def _run_with_cleanup(post_id: str, channel_id: str, user_id: str,
                     project_name: str, user_text: str):
    try:
        run_agentic_workflow(
            channel_id=channel_id,
            root_id=post_id,
            project_name=project_name,
            user_id=user_id,
            initial_task=user_text
        )
    finally:
        _running_tasks.discard(post_id)
