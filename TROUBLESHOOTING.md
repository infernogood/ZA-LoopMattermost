# Troubleshooting — Хроника ошибок и их решений

## 1. `NameError: name 'GraphState' is not defined`

**Симптом:** uvicorn падает сразу при старте.

**Причина:** Класс `GraphState(TypedDict)` определён в конце файла (строка 236), но функции `post_agent_message`, `post_handoff`, `notify_mm` используют его как type hint раньше по файлу. Python 3.10 требует, чтобы имя было определено до использования в аннотации.

**Решение (два варианта):**
- **Вариант A (на сервере):** переместить `class GraphState` выше всех функций, которые его используют.
- **Вариант B (в репозитории):** добавить `from __future__ import annotations` — все аннотации становятся lazy-строками, порядок определений не важен.

Выбран вариант B как более чистый.

---

## 2. `ValueError: Graph must have an entrypoint`

**Симптом:** `langgraph` выбрасывает ValueError при компиляции графа.

**Причина:** Граф использует `StateGraph`, но не содержит ребра `START → stage_1_researcher`. LangGraph требует явного указания точки входа.

**Решение:** Добавить импорт `START` и ребро:
```python
from langgraph.graph import StateGraph, START, END

workflow.add_edge(START, "stage_1_researcher")
```

Также удалены дублирующиеся рёбра `stage_4_validator → stage_5_final` и `stage_5_final → END`, которые остались от первой версии.

---

## 3. `User=ai-orchestrator` — пользователь не существует

**Симптом:** `status=203/EXEC` — uvicorn не запускается.

**Причина:** В `ai-orchestrator.service` указан `User=ai-orchestrator`, но такой пользователь не создан в системе.

**Решение:** Изменить на `User=root` (или создать пользователя `ai-orchestrator`).

---

## 4. Channel API — 404 Not Found

**Симптом:** В логах `Failed to resolve channel 'ai-researcher'` с HTTP 404.

**Причина:** Неправильный URL Mattermost API v4:
```
# Было (неправильно):
/api/v4/channels/name/{team}/{channel}

# Стало (правильно):
/api/v4/teams/name/{team}/channels/name/{channel}
```

Mattermost API v4 использует `/teams/name/{team}/channels/name/{channel}` для поиска канала по имени команды и handle канала.

---

## 5. `400 Bad Request` — root_id = null

**Симптом:** `_post_to_channel` возвращает 400.

**Причина:** В `notify_mm()` поле `root_id` всегда включается в payload, даже если оно `None`. Mattermost API не принимает `null` для `root_id`.

**Решение:** Делать `root_id` conditional:
```python
payload = {"channel_id": state["channel_id"], "message": msg}
if state.get("root_id"):
    payload["root_id"] = state["root_id"]
```

---

## 6. `with_structured_output()` — Z.AI не поддерживает

**Симптом:** `ValidationError: Invalid JSON: expected value at line 1 column 1` — LLM возвращает не-JSON.

**Причина:** Метод `ChatOpenAI.with_structured_output()` ожидает от модели строгий JSON, но Z.AI (GLM) не гарантирует валидный JSON на выходе.

**Решение:** Убрать `with_structured_output`, заменить на ручной парсинг:

```python
def _parse_debug_result(response_text: str) -> DebugResult:
    import json as json_lib
    text = response_text.strip()
    # Попытка извлечь JSON из текста
    json_match = re.search(r'\{[^{}]*"has_errors"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            parsed = json_lib.loads(json_match.group())
            return DebugResult(has_errors=bool(parsed.get("has_errors", False)), ...)
        except Exception:
            pass
    # Fallback — поиск ключевых слов об ошибках
    has_err = any(word in text.lower() for word in ["ошибк", "error", "bug", ...])
    return DebugResult(has_errors=has_err, ...)
```

Теперь Debugger использует обычный `llm_invoke("debugger", messages)` + `_parse_debug_result()`.

---

## 7. `TimeoutError: LLM call timed out after 180s`

**Симптом:** LLM вызовы падают по таймауту.

**Причина:** Z.AI может отвечать дольше 180 секунд (особенно при высокой нагрузке).

**Решение:** Увеличить таймаут и читать из `.env`:
```python
LLM_CALL_TIMEOUT = int(os.environ.get("LLM_CALL_TIMEOUT", "300"))
```

---

## 8. `The 'python-multipart' library must be installed`

**Симптом:** `AssertionError: The 'python-multipart' library must be installed to use form parsing.`

**Причина:** FastAPI `request.form()` требует библиотеку `python-multipart` для парсинга form-urlencoded данных. Mattermost отправляет вебхуки и slash-команды именно в этом формате.

**Решение:** Добавить `python-multipart>=0.0.9` в `requirements.txt` и установить на сервере.

---

## 9. Mattermost не может достучаться до сервера (502 / молчание)

**Симптом:** 
- `Command with a trigger of 'project' failed.`
- `ai_lead` не отвечает.
- Из тестового alpine-контейнера (в той же сети Docker) запросы работают.

**Причина:** **Три слоя проблем:**

### 9a. Ошибка в URL API Mattermost (см. п.4)

Исправлено: `/api/v4/teams/name/{team}/channels/name/{channel}`.

### 9b. Uvicorn слушал на неправильном IP

В `ai-orchestrator.service` было `--host 172.17.0.1`, но:
- Docker-сеть Mattermost — `docker_default` с gateway `172.18.0.1`
- Адрес `172.17.0.1` принадлежит интерфейсу `docker0` (другая сеть)

**Решение:** `--host 0.0.0.0` (слушать на всех интерфейсах).

### 9c. Mattermost блокирует outgoing webhooks на private IP

**Самая коварная причина.** Mattermost по умолчанию не отправляет вебхуки на private IP-адреса (RFC 1918: 10.x.x.x, 172.16-31.x.x, 192.168.x.x). Даже если сеть Docker работает и сервер доступен — Mattermost отбрасывает запрос на уровне приложения.

Проверка: из alpine-контейнера `curl http://172.18.0.1:8000/slash` возвращает 200 OK, но из Mattermost — тишина.

**Решение:** Добавить `172.18.0.1` в список разрешённых internal connections:

**Способ A — через System Console (если есть доступ):**
System Console → Environment → Web Server → `Allow untrusted internal connections to` → добавить `172.18.0.1`

**Способ B — через config.json:**
```bash
# Найти config.json
find /root/docker -name "config.json"

# Добавить в ServiceSettings.AllowedUntrustedInternalConnections
```

**Способ C — через переменную окружения (если есть в docker-compose):**
```yaml
# В docker-compose.yml, секция mattermost → environment:
- MM_SERVICESETTINGS_ALLOWEDUNTRUSTEDINTERNALCONNECTIONS=172.18.0.1
```

```bash
# В .env:
MM_SERVICESETTINGS_ALLOWEDUNTRUSTEDINTERNALCONNECTIONS=172.18.0.1
```

---

## 10. Docker compose: порты пропали после перезапуска

**Симптом:** Mattermost стал недоступен (`Connection refused` на порту 8065).

**Причина:** В `docker-compose.yml` **нет** секции `ports:`. Порты описаны в отдельных файлах:
- `docker-compose.without-nginx.yml` — только mattermost на порту 8065
- `docker-compose.nginx.yml` — mattermost + nginx на портах 80/443

Запуск `docker compose up -d mattermost` без указания дополнительного compose-файла поднял контейнер без портов.

**Как было изначально:**
```bash
docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml up -d
```

**Решение:** Всегда запускать с полным набором файлов:
```bash
docker compose -f docker-compose.yml -f docker-compose.without-nginx.yml up -d
```
Или (если есть nginx):
```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d
```

---

## Итоговая схема сетевого взаимодействия

```
┌─────────────────────────────────────────────────────┐
│                    Хост (Ubuntu)                     │
│                                                      │
│  uvicorn (0.0.0.0:8000)                              │
│  nginx (0.0.0.0:80/443) — системный, не Docker       │
│                                                      │
│  br-e0d31f62cfe1 (172.18.0.1/16)                    │
│       │                                              │
│       ▼                                              │
│  ┌────────────────────┐                              │
│  │ Mattermost         │                              │
│  │ 172.18.0.3:8065    │                              │
│  │                     │                              │
│  │ POST /slash ───────► 172.18.0.1:8000              │
│  │ POST /webhook ─────► 172.18.0.1:8000              │
│  └────────────────────┘                              │
└─────────────────────────────────────────────────────┘

Ключевые условия работоспособности:
1. uvicorn на 0.0.0.0:8000
2. Callback URL = http://172.18.0.1:8000/...
3. MM_SERVICESETTINGS_ALLOWEDUNTRUSTEDINTERNALCONNECTIONS = 172.18.0.1
4. python-multipart установлен
5. Правильный API URL: /api/v4/teams/name/{team}/channels/name/{channel}
```
