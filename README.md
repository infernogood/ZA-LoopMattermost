# AI Orchestrator — Managed Loop Engineering Pipeline (Mattermost)

Мультиагентная система "Controlled Loop Engineering" на базе LangGraph и Z.AI (GLM).  
Оркестрирует 5 ИИ-агентов через Mattermost: каждый агент пишет в свой канал,  
пользователь видит сквозную переписку и передачу задач между агентами.

---

## Архитектура

### Жизненный цикл обработки задачи

```
Пользователь                          Mattermost                         FastAPI + LangGraph
    │                                     │                                   │
    ├─ POST /webhook ─────────────────────►│                                   │
    │   (text = "Напиши CLI утилиту")      │                                   │
    │                                     ├─ background_tasks.add_task() ─────►│
    │◄── HTTP 200 OK ─────────────────────┤                                   │
    │                                     │                                   ▼
    │                                     │                         run_agentic_workflow()
    │                                     │                              │
    │                                     │                              ├─ write plan.md
    │                                     │                              ├─ Stage 1: Researcher
    │◄── [Stage 1] Research ──────────────┤                              │   → ai-researcher
    │                                     │                              ├─ Stage 2: Programmer
    │◄── [Stage 2] Programmer ────────────┤                              │   → ai-programmer
    │                                     │                              ├─ Stage 3: Debugger
    │◄── [Stage 3] Debug ─────────────────┤                              │   → ai-debugger
    │                                     │                              │   ├─ errors → loop Stage 2
    │◄── [Loop] → ai-control ─────────────┤                              │   └─ ok → Stage 4
    │                                     │                              ├─ Stage 4: Validator
    │◄── [Stage 4] Validator ─────────────┤                              │   → ai-validator
    │                                     │                              ├─ Stage 5: Reporter
    │◄── [Stage 5] Result ────────────────┤                              │   → ai-reporter
    │◄── ✅ Pipeline Complete ────────────┤                              └─ → user thread
```

### Схема multi-channel UX

```
┌─────────────────────────────────────────────────────────────────┐
│  #ai-engineering-factory (канал пользователя)                   │
│                                                                 │
│  User: @ai Напиши парсер CSV                                    │
│  Bot: ✅ Pipeline Complete (итераций: 0/3)                      │
│       Наблюдать: ~ai-researcher | ~ai-programmer | ...          │
└─────────────────────────────────────────────────────────────────┘

┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│ #ai-researcher     │  │ #ai-programmer     │  │ #ai-debugger       │
│                    │  │                    │  │                    │
│ Bot: Анализирую    │  │ @Programmer —      │  │ @Debugger —        │
│ задачу...          │  │ задача от          │  │ код от Programmer  │
│                    │  │ Researcher         │  │                    │
│ Bot: Анализ        │  │                    │  │ Bot: Проверяю код  │
│ завершён           │  │ Bot: Пишу код...   │  │                    │
│              ─────►│  │              ─────►│  │  ───► errors → loop
│                    │  │ Bot: Код написан   │  │  ───► ok → val     │
└────────────────────┘  └────────────────────┘  └────────────────────┘

┌────────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│ #ai-validator      │  │ #ai-reporter       │  │ #ai-control        │
│                    │  │                    │  │                    │
│ @Validator —       │  │ @Reporter —        │  │ Bot: Loop итерация │
│ код от Debugger    │  │ валидация пройдена  │  │ 1/3 — возврат     │
│                    │  │                    │  │ программисту       │
│ Bot: Валидирую...  │  │ Bot: Формирую      │  │                    │
│                    │  │ отчёт...           │  │ Bot: Guardrail     │
│ Bot: Валидация     │  │                    │  │ лимит 3/3          │
│ завершена          │  │ Bot: Финальный     │  │                    │
│              ─────►│  │ отчёт              │  │                    │
└────────────────────┘  └────────────────────┘  └────────────────────┘
```

### Технологический стек

| Компонент | Технология | Роль |
|-----------|-----------|------|
| API-шлюз | FastAPI + Uvicorn | Приём вебхуков от Mattermost |
| Оркестратор | LangGraph (StateGraph) | Маршрутизация агентов по State Machine |
| ИИ-провайдер | Z.AI GLM-5.2 (api.z.ai) | Генерация кода, отладка, валидация |
| Файловая система | /var/lib/ai-workspace/ | Межпроцессное взаимодействие (файлы) |
| Демонизация | systemd | High Availability, auto-restart |

---

## Файловая структура

```
/opt/ai-orchestrator/
├── main.py                    # FastAPI — вебхук + slash-команды
├── graph.py                   # LangGraph — 5 агентов + роутер
├── projects.py                # CRUD проектов + файловый I/O
├── requirements.txt           # Python-зависимости
├── .env                       # (создаётся из .env.example)
├── .env.example               # Шаблон конфигурации
├── .gitignore
├── ai-orchestrator.service    # systemd unit
├── GIT_WORKFLOW.md            # Инструкция по git push/pull
├── default-prompts/           # Глобальные дефолтные промты агентов
│   ├── researcher-prompt.md
│   ├── programmer-prompt.md
│   ├── debugger-prompt.md
│   └── validator-prompt.md
└── venv/                      # Виртуальное окружение Python

/var/lib/ai-workspace/
└── projects/
    ├── .active                # JSON: {user_id: active_project}
    ├── my-app/
    │   ├── meta.json          # Метаданные проекта
    │   ├── plan.md            # Append-only: все задачи
    │   ├── context.md         # Append-only: контекст итераций
    │   ├── status.md          # Append-only: статусы этапов
    │   ├── error.md           # Append-only: ошибки
    │   ├── src/               # Сгенерированный код
    │   │   ├── main.py
    │   │   └── errors.md
    │   └── prompts/           # Проект-специфичные промты
    │       └── programmer-prompt.md
    └── another-project/
        └── ...
```

---

## Предварительные требования

- **Ubuntu 22.04 LTS**
- **Python 3.10+**
- **Mattermost** (уже установлен, работает на `http://127.0.0.1:8065`)
- **Redis** (для воркера RQ — опционально, можно заменить на BackgroundTasks)
- **Z.AI API ключ** — [получить](https://z.ai/manage-apikey/apikey-list)

---

## Установка

### 1. Клонирование репозитория

```bash
# 1. Настроить SSH-ключ в GitHub:
#    - Скопировать публичный ключ с сервера: cat ~/.ssh/id_ed25519.pub
#    - Добавить в github.com/settings/keys (Authentication Key)
#    - Проверить: ssh -T git@github.com  → "Hi infernogood! You've successfully authenticated"

# 2. Клонировать репозиторий
cd /opt
git clone git@github.com:infernogood/ZA-LoopMattermost.git ai-orchestrator
cd ai-orchestrator

# 3. Виртуальное окружение и зависимости
python3 -m venv venv
source venv/bin/activate
pip install --no-cache-dir -r requirements.txt
```

### 2. Файловая система

```bash
sudo mkdir -p /var/lib/ai-workspace/projects
sudo chown -R $USER:$USER /var/lib/ai-workspace
sudo chmod 750 /var/lib/ai-workspace
```

### 3. Конфигурация (.env)

```bash
cp .env.example .env
nano .env
```

Обязательные переменные:

| Переменная | Значение |
|-----------|----------|
| `DEFAULT_API_KEY` | Ключ Z.AI (fallback для всех агентов) |
| `MATTERMOST_BOT_TOKEN` | Токен бота Mattermost |
| `MATTERMOST_TEAM_NAME` | `ai-engineering-factory` |

Опционально — пер-агентные LLM (переопределяют DEFAULT):

```
PROGRAMMER_MODEL=glm-5.2
PROGRAMMER_PROVIDER=zai
PROGRAMMER_API_KEY=
PROGRAMMER_TEMPERATURE=0.0
```

Доступные префиксы: `RESEARCHER_`, `PROGRAMMER_`, `DEBUGGER_`, `VALIDATOR_`, `REPORTER_`.

Поддерживаемые провайдеры: `zai`, `openai`, `anthropic`.

### 4. Настройка Mattermost

#### 4a. Создать Bot Account

1. **System Console → Integrations → Bot Accounts** → Enable
2. **Integrations → Bot Accounts → Add Bot Account**
   - Username: `ai-orchestrator`
   - Display Name: `AI Orchestrator`
   - Description: `Multi-agent engineering pipeline`
   - Role: Member
3. После создания скопировать **Access Token** → вставить в `.env` как `MATTERMOST_BOT_TOKEN`

#### 4b. Создать каналы агентов

В команде `ai-engineering-factory` создать каналы с **handle names**:

| Канал | Handle |
|-------|--------|
| AI Researcher | `ai-researcher` |
| AI Programmer | `ai-programmer` |
| AI Debugger | `ai-debugger` |
| AI Validator | `ai-validator` |
| AI Reporter | `ai-reporter` |
| AI Control | `ai-control` |

Добавить бота `ai-orchestrator` во все каналы с ролью Member.

#### 4c. Настроить Slash Command (управление проектами)

1. **Integrations → Slash Commands → Add Slash Command**
   - Title: `AI Project`
   - Command Trigger Word: `/project`
   - Callback URLs: `http://172.17.0.1:8000/slash`
   - Request Method: `POST`
   - Autocomplete: ✓

Доступные команды: `/project create <name>`, `/project select <name>`, `/project list`.

> **Request URL:** используй тот же IP, что и для вебхука (см. примечание ниже).

#### 4d. Настроить Outgoing Webhook (запуск пайплайна)

1. **Integrations → Outgoing Webhooks → Add Outgoing Webhook**
   - Title: `AI Engineering Trigger`
   - Channel: `ai-engineering-factory`
   - Trigger When: `Words start with a message`
   - Trigger Word: `ai_lead`
   - Callback URLs: `http://172.17.0.1:8000/webhook`
   - Content Type: `application/json`

> **Какой URL использовать?** — это зависит от Docker-сети Mattermost.
> Проверь: `docker network inspect docker_default | grep Gateway` (обычно `172.18.0.1`).
> Для сети `docker_default` используй `http://172.18.0.1:8000/webhook`.
> Для сети `docker0` используй `http://172.17.0.1:8000/webhook`.
> Если Mattermost НЕ в Docker (работает напрямую на хосте): `http://127.0.0.1:8000/webhook`.

### 5. Запуск через systemd

```bash
sudo cp ai-orchestrator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-orchestrator
sudo systemctl start ai-orchestrator

# Проверка
sudo systemctl status ai-orchestrator
journalctl -u ai-orchestrator -f
```

### 6. Запуск вручную (отладка)

```bash
cd /opt/ai-orchestrator
source venv/bin/activate
DEFAULT_API_KEY=... MATTERMOST_BOT_TOKEN=... MATTERMOST_TEAM_NAME=ai-engineering-factory \
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Руководство пользователя

### Быстрый старт

```
# 1. Создать проект (однократно)
/project create my-app

# 2. Поставить задачу
ai_lead Напиши парсер CSV на Python
```

После этого открой каналы `~ai-researcher`, `~ai-programmer`, `~ai-debugger`, `~ai-validator`, `~ai-reporter` — агенты будут писать туда по ходу работы.

Когда пайплайн завершится, бот пришлёт `Pipeline Complete` в общий канал.

---

### Понятие проекта

Проект — это изолированная рабочая директория, в которой хранятся все данные:

- **plan.md** — все задачи, которые ставились (append-only)
- **context.md** — контекст итераций (append-only)
- **status.md** — логи статусов этапов (append-only)
- **error.md** — логи ошибок (append-only)
- **src/** — сгенерированный код
- **prompts/** — кастомные промпты для конкретного проекта

Без активного проекта задача через `ai_lead` не запустится (ответ `no_project`).

---

### Управление проектами

Все команды вводятся в канале `#ai-engineering-factory`:

| Команда | Описание |
|---------|----------|
| `/project create <name>` | Создать новый проект и сразу сделать его активным |
| `/project select <name>` | Переключиться на существующий проект |
| `/project list` | Показать все проекты, активный помечен `← active` |

Проект привязывается к `user_id` — у каждого пользователя может быть свой активный проект.

---

### Запуск задачи

1. Убедись, что проект активен: `/project list` (активный помечен `← active`)
2. Если проект не выбран: `/project select <name>`
3. Отправь задачу:

```
ai_lead <описание задачи>
```

Примеры задач:

```
ai_lead Напиши CLI-утилиту для конвертации JSON в YAML с поддержкой вложенных структур
ai_lead Добавь в main.py обработку аргументов через argparse
ai_lead Исправь баг: при пустом файле программа падает с IndexError
```

---

### Что происходит после ai_lead

1. **FastAPI** проверяет наличие активного проекта
2. Создаётся workspace проекта (если ещё не создан)
3. Задача дописывается в `plan.md`
4. Запускается пайплайн из 5 этапов:

| Этап | Агент | Канал | Результат |
|------|-------|-------|-----------|
| 1 | Researcher | `#ai-researcher` | Анализ задачи, план |
| 2 | Programmer | `#ai-programmer` | Генерация/исправление кода в `src/` |
| 3 | Debugger | `#ai-debugger` | Проверка кода, JSON-отчёт об ошибках |
| 4 | Validator | `#ai-validator` | Сверка кода с планом |
| 5 | Reporter | `#ai-reporter` | Финальный отчёт со списком файлов |

5. После завершения — `Pipeline Complete` в общий канал

Если Debugger находит ошибки, Programmer запускается снова (до 3 итераций).
Решение о возврате публикуется в `#ai-control`.

---

### Наблюдение за агентами

Открой каналы параллельно, чтобы видеть процесс в реальном времени:

- **`#ai-researcher`** — как агент понял задачу, какие технологии выбрал
- **`#ai-programmer`** — какие файлы созданы/изменены, размер кода
- **`#ai-debugger`** — найденные ошибки или "код чист"
- **`#ai-validator`** — прошёл ли код проверку
- **`#ai-reporter`** — итоговый отчёт
- **`#ai-control`** — системные сообщения: loop, guardrail

Каналы можно свернуть/развернуть по необходимости.

---

### Кастомные промпты

Для каждого проекта можно переопределить системный промпт любого агента.

Создай файл в директории проекта на сервере:

```
/var/lib/ai-workspace/projects/<project>/prompts/<agent>-prompt.md
```

Например, `programmer-prompt.md`:

```markdown
Ты — senior Python-разработчик. Пиши код в стиле FastAPI.
Всегда добавляй type hints. Используй pydantic для валидации.
Формат вывода: ```filepath:src/<filename>
<code>
```
```

Доступные агенты: `researcher`, `programmer`, `debugger`, `validator`.

Порядок загрузки промпта:
1. `projects/<project>/prompts/<agent>-prompt.md` — per-project
2. `/opt/ai-orchestrator/default-prompts/<agent>-prompt.md` — глобальный
3. Встроенный fallback в коде

---

### Per-agent LLM

Каждый агент может использовать свою модель, провайдер и температуру.
Настройка в `.env` на сервере:

```ini
# Programmer — своя модель
PROGRAMMER_MODEL=glm-5.2
PROGRAMMER_PROVIDER=zai
PROGRAMMER_API_KEY=
PROGRAMMER_TEMPERATURE=0.0

# Researcher — более креативный
RESEARCHER_TEMPERATURE=0.3
```

Если пер-агентная переменная не задана, используется `DEFAULT_MODEL`, `DEFAULT_PROVIDER`, `DEFAULT_API_KEY`.

---

### Типичный сценарий

```
# 1. Создать проект под идею
/project create csv-tools

# 2. Поставить первую задачу
ai_lead Напиши конвертер CSV → JSON с поддержкой вложенных ключей

# 3. (наблюдаешь в каналах агентов)
# 4. Получаешь Pipeline Complete
# 5. Проверяешь src/main.py

# 6. Ставишь следующую задачу в тот же проект
ai_lead Добавь поддержку аргумента --indent для форматирования JSON

# 7. (агенты продолжают в том же workspace)
```

---

### Список файлов

Посмотреть сгенерированные файлы на сервере:

```bash
ls -la /var/lib/ai-workspace/projects/<name>/src/
cat /var/lib/ai-workspace/projects/<name>/status.md   # лог этапов
cat /var/lib/ai-workspace/projects/<name>/error.md     # лог ошибок
cat /var/lib/ai-workspace/projects/<name>/plan.md      # все задачи
```

---

### Troubleshooting

| Симптом | Причина | Решение |
|---------|---------|---------|
| `ai_lead` молча не реагирует | Нет активного проекта | `/project select <name>` |
| "Канал ai-researcher не найден" | Бот не добавлен в канал | `/invite @ai-orchestrator` |
| `plan.md` пуст | Не передан текст задачи | `ai_lead <текст>` |
| "LLM call timed out" | Модель отвечает >180с | Увеличить `LLM_CALL_TIMEOUT` |
| "Stage X FAILED" | Ошибка в этапе | `journalctl -u ai-orchestrator -f` |
| Нейронки не пишут в каналы | API ключ неверный | Проверить `DEFAULT_API_KEY` в `.env` |

---

## Механизм Loop (Debug → Programmer)

```
stage_3_debugger
    │
    ├── has_errors=True, loop_count < 3 ───► stage_2_programmer (loop)
    │   post_handoff("debugger", "programmer", "В коде найдены ошибки...")
    │   post_agent_message("control", "Loop итерация N/3")
    │
    ├── has_errors=True, loop_count >= 3 ───► stage_4_validator (guardrail)
    │   post_agent_message("control", "Guardrail: лимит 3/3")
    │
    └── has_errors=False ──────────────────► stage_4_validator (ok)
        post_handoff("debugger", "validator", "Код чист")
```

**Защита:** хард-лимит 3 итерации. При превышении — принудительный переход
к валидации с уведомлением в `#ai-control`.

---

## Агенты и их промпты

### Системные промпты (порядок загрузки)

1. `projects/{name}/prompts/{agent}-prompt.md` — per-project override
2. `default-prompts/{agent}-prompt.md` — глобальные дефолты
3. Встроенный fallback (хардкод в `_create_default_prompt()`)

### Per-agent LLM

Каждый агент использует свою модель/провайдер/температуру (задаётся в `.env`).
Если пер-агентная переменная не задана — используется `DEFAULT_*`.

| Stage | Агент | Переменная префикс | Temperature | Что делает |
|-------|-------|-------------------|-------------|------------|
| 1 | Researcher | `RESEARCHER_` | 0.3 | Анализирует задачу, составляет план |
| 2 | Programmer | `PROGRAMMER_` | 0.0 | Пишет/исправляет код |
| 3 | Debugger | `DEBUGGER_` | 0.0 | Проверяет на ошибки, возвращает JSON |
| 4 | Validator | `VALIDATOR_` | 0.0 | Сверяет с планом (не перезаписывает код!) |
| 5 | Reporter | `REPORTER_` | — | Формирует финальный отчёт |

---

## Конфигурация (.env)

### Default (fallback)

| Переменная | Обязательная | По умолчанию | Описание |
|-----------|-------------|-------------|----------|
| `DEFAULT_MODEL` | Да | `glm-5.2` | Модель LLM по умолчанию |
| `DEFAULT_PROVIDER` | Да | `zai` | Провайдер (`zai`, `openai`, `anthropic`) |
| `DEFAULT_API_KEY` | Да | — | API ключ |
| `MATTERMOST_BOT_TOKEN` | Да | — | Токен бота Mattermost |
| `MATTERMOST_TEAM_NAME` | Да | `ai-engineering-factory` | Название команды Mattermost |
| `MATTERMOST_URL` | Нет | `http://127.0.0.1:8065` | Базовый URL Mattermost |
| `LLM_CALL_TIMEOUT` | Нет | `180` | Таймаут LLM-вызова (сек) |

### Per-agent override (опционально)

Любой из префиксов `RESEARCHER_`, `PROGRAMMER_`, `DEBUGGER_`, `VALIDATOR_`, `REPORTER_`
можно комбинировать с суффиксами `_MODEL`, `_PROVIDER`, `_API_KEY`, `_TEMPERATURE`.

Пример — для Programmer своя модель и температура:

```
PROGRAMMER_MODEL=glm-5.2
PROGRAMMER_PROVIDER=zai
PROGRAMMER_API_KEY=
PROGRAMMER_TEMPERATURE=0.0
```

---

## Безопасность

- `.env` файл — `chmod 600`, не включается в git
- Все file operations — `encoding='utf-8'` явно
- Запись файлов: временный файл → `os.fsync()` → `os.replace()` (атомарность)
- Путь workspace валидируется `_SAFE_PATH_RE` — `/../../etc/passwd` не пройдёт
- Чтение файлов: лимит 512KB, превышение → truncation
- Rate limiter: 2 запроса на канал в 10 секунд
- Дедупликация: один post_id → один активный workflow
- Sanitize post_id: только `[a-zA-Z0-9_\-]`
- Message truncation: обрезка до 16383 символов (лимит Mattermost)
- Thread-safe `_channel_cache` через `threading.Lock`
- Fallback при недоступности канала агента → сообщение в канал пользователя

---

## Защита от ошибок

| Слой | Механизм |
|------|---------|
| LLM таймаут | `ThreadPoolExecutor` + `future.result(timeout=180)` |
| Error boundary | `_safe_stage()` — catch Exception на каждом узле графа |
| Crash уведомление | `post_agent_message()` + `notify_mm()` + `write_file(error.md)` |
| Router crash | `try/except` → stage_4_validator по умолчанию |
| Пустой response LLM | fallback-сообщение вместо краша |
| Loop guardrail | max 3 итерации, принудительный выход |
| Mattermost retry | 3 попытки с exponential backoff (1.5^N) |
| Graceful shutdown | SIGTERM handler + `os._exit(0)` |

---

## Мониторинг

```bash
# Логи через journald
journalctl -u ai-orchestrator -f --output=json

# Проверка здоровья
curl http://127.0.0.1:8000/webhook -X POST -H "Content-Type: application/json" \
  -d '{"channel_id":"test","post_id":"test","text":"health check","user_name":"test"}'

# Redis очередь (если используется RQ)
rq info --url redis://127.0.0.1:6379
```

---

## Зависимости (requirements.txt)

```
fastapi>=0.111.0       # HTTP API
uvicorn[standard]>=0.29.0  # ASGI сервер
langgraph>=0.1.0       # State Machine граф
langchain-openai>=0.1.0  # OpenAI-совместимый клиент (Z.AI)
langchain-core>=0.1.0  # Базовые абстракции LangChain
requests>=2.31.0       # HTTP-клиент для Mattermost REST API
pydantic>=2.0.0        # Валидация данных
python-dotenv>=1.0.0   # Загрузка .env
```


