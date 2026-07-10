# Изменения проекта AI Orchestrator

## 1. `ai-orchestrator.service` — systemd service

**Проблема:** `NameError: name 'GraphState' is not defined` при запуске, затем `status=217/USER`.

**Исправление:**
```diff
- User=ai-orchestrator
- Group=ai-orchestrator
+ User=root
+ Group=root
```

**Причина:** Пользователь `ai-orchestrator` не существовал в системе. Можно использовать `root` или создать пользователя.

---

## 2. `graph.py` — оркестратор агентов

### 2.1. Перемещение `GraphState` вверх

**Проблема:** `NameError: name 'GraphState' is not defined` — класс использовался до объявления.

**Исправление:** Переместил класс `GraphState` перед функциями, которые его используют (строки ~38-48).

```python
class GraphState(TypedDict):
    channel_id: str
    root_id: str
    workspace_path: str
    loop_count: int
    has_errors: bool
```

### 2.2. Добавление импорта `START` и ребра

**Проблема:** `ValueError: Graph must have an entrypoint: add at least one edge from START to another node`.

**Исправление:**
```diff
from langgraph.graph import StateGraph, START, END

# После добавления узлов:
+ workflow.add_edge(START, "stage_1_researcher")
workflow.add_edge("stage_1_researcher", "stage_2_programmer")
```

### 2.3. Исправление URL для Mattermost API

**Проблема:** `404 Not Found` для `/api/v4/channels/name/ai-engineering-factory/ai-researcher`.

**Исправление:** Исправлен URL в функции `_resolve_channel_id()`:
```diff
- url = f"{MATTERMOST_URL}/api/v4/channels/name/{MATTERMOST_TEAM_NAME}/{channel_name}"
+ url = f"{MATTERMOST_URL}/api/v4/teams/name/{MATTERMOST_TEAM_NAME}/channels/name/{channel_name}"
```

**Причина:** Mattermost API v4 использует `/teams/name/{team}/channels/name/{channel}`.

### 2.4. Исправление `root_id` в `notify_mm()`

**Проблема:** `400 Bad Request` при отправке сообщений.

**Исправление:** Добавлен conditional для `root_id`:
```diff
  headers = {"Authorization": f"Bearer {bot_token}"}
  payload = {
      "channel_id": state["channel_id"],
      "message": _truncate_message(message),
-     "root_id": state["root_id"]
  }
+ if state.get("root_id"):
+     payload["root_id"] = state["root_id"]
```

**Причина:** Mattermost API не принимает `null` для `root_id`.

### 2.5. Удаление `with_structured_output` и добавление ручного парсинга JSON

**Проблема:** `ValidationError: Invalid JSON: expected value at line 1 column 1` — Z.AI не поддерживает `with_structured_output()`.

**Исправление:**
- Удалено: `llm_debugger_structured = llm_debugger.with_structured_output(DebugResult)`
- Добавлена функция `_parse_debug_result()` для парсинга JSON вручную:
```python
def _parse_debug_result(response_text: str) -> DebugResult:
    """Пытается извлечь JSON из ответа LLM. Если не удаётся — парсит по ключевым словам."""
    import json as json_lib
    text = response_text.strip()
    json_match = re.search(r'\{[^{}]*"has_errors"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            parsed = json_lib.loads(json_match.group())
            return DebugResult(
                has_errors=bool(parsed.get("has_errors", False)),
                error_description=parsed.get("error_description", "")
            )
        except (json_lib.JSONDecodeError, Exception):
            pass
    has_err = any(word in text.lower() for word in ["ошибк", "error", "bug", "неправильн", "некоррект"])
    return DebugResult(
        has_errors=has_err,
        error_description=text[:500] if has_err else ""
    )
```
- Изменён `stage_3_debugger()` для использования обычного LLM вызова с ручным парсингом.

### 2.6. Увеличение и читаемость таймаута LLM

**Проблема:** `TimeoutError: LLM call timed out after 180s`.

**Исправление:**
```diff
- LLM_CALL_TIMEOUT = 180
+ LLM_CALL_TIMEOUT = int(os.environ.get("LLM_CALL_TIMEOUT", "300"))
```

**Причина:** Z.AI может отвечать дольше. Дефолт увеличен до 300с, теперь читается из env.

---

## 3. `main.py` — FastAPI webhook handler

**Проблема:** `400 Bad Request` — Mattermost отправляет `form-urlencoded`, а не JSON.

**Исправление:** Добавлена поддержка обоих форматов:
```diff
  content_type = request.headers.get("content-type", "")
  try:
-     data = await request.json()
+     if "application/json" in content_type:
+         data = await request.json()
+     else:
+         form = await request.form()
+         data = dict(form)
  except Exception:
      raise HTTPException(status_code=400, detail="Invalid request body")
```

**Причина:** Mattermost outgoing webhooks отправляют `form-urlencoded` по умолчанию.

---

## 4. Конфигурация сервера

### 4.1. Изменение хоста в systemd service

**Проблема:** Mattermost в Docker сети `docker_default` с gateway `172.18.0.1`, но сервер слушал на `172.17.0.1`.

**Исправление:** Изменён хост на `0.0.0.0`:
```bash
sudo sed -i 's/--host 172.17.0.1/--host 0.0.0.0/' /etc/systemd/system/ai-orchestrator.service
sudo systemctl daemon-reload
sudo systemctl restart ai-orchestrator
```

### 4.2. Callback URL в Mattermost Outgoing Webhook

**Проблема:** Вебхук не доходит до сервера.

**Исправление:** Callback URL должен быть `http://172.18.0.1:8000/webhook` (gateway сети `docker_default`).

---

## 5. Настройка каналов Mattermost

### 5.1. Создание каналов

В команде `ai-engineering-factory` созданы каналы:
- `ai-researcher`
- `ai-programmer`
- `ai-debugger`
- `ai-validator`
- `ai-reporter`
- `ai-control`

Бот `ai-orchestrator` добавлен во все каналы с ролью Member.

### 5.2. Настройка Outgoing Webhook

- Title: `AI Engineering Trigger`
- Channel: `ai-engineering-factory`
- Trigger When: `Words start with a message`
- Trigger Word: `ai_lead`
- Callback URLs: `http://172.18.0.1:8000/webhook`
- Content Type: `application/json`

---

## 6. Рекомендации по `.env`

Опциональные переменные:
```
LLM_CALL_TIMEOUT=300  # или 600 для долгих запросов
MATTERMOST_URL=http://127.0.0.1:8065
```

Обязательные:
```
ZAI_API_KEY=<ваш ключ>
MATTERMOST_BOT_TOKEN=<токен бота>
MATTERMOST_TEAM_NAME=ai-engineering-factory
```

---

## 7. Траблшутинг

**Вебхук не доходит:** проверьте Callback URL и сеть Docker.
**400 Bad Request:** бот не добавлен в канал.
**TimeoutError:** увеличьте `LLM_CALL_TIMEOUT`.
**Канал не найден (404):** создайте каналы агентов.
**403 Forbidden:** `/invite @ai-orchestrator` в канале.