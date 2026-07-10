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
├── main.py                    # FastAPI — вебхук Mattermost
├── graph.py                   # LangGraph — 5 агентов + роутер
├── requirements.txt           # Python-зависимости
├── .env                       # (создаётся из .env.example)
├── .env.example               # Шаблон конфигурации
├── .gitignore
├── ai-orchestrator.service    # systemd unit (копируется в /etc/systemd/system/)
└── venv/                      # Виртуальное окружение Python

/var/lib/ai-workspace/         # Рабочие директории тредов
├── thread_{post_id_1}/
│   ├── plan.md                # Исходная задача пользователя
│   ├── context.md             # Сгенерированный код
│   ├── error.md               # Логи ошибок (при цикле отладки)
│   └── status.md              # Текущий статус этапа
└── thread_{post_id_2}/
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

### 1. Клонирование и подготовка окружения

```bash
sudo mkdir -p /opt/ai-orchestrator
sudo chown -R $USER:$USER /opt/ai-orchestrator

# Копировать файлы проекта в /opt/ai-orchestrator/
cp -r * /opt/ai-orchestrator/
cd /opt/ai-orchestrator

python3 -m venv venv
source venv/bin/activate
pip install --no-cache-dir -r requirements.txt
```

### 2. Файловая система

```bash
sudo mkdir -p /var/lib/ai-workspace
sudo chown $USER:$USER /var/lib/ai-workspace
sudo chmod 750 /var/lib/ai-workspace
```

Опционально — tmpfs для скорости (актуально при частых запросах):

```bash
# Добавить в /etc/fstab:
tmpfs /var/lib/ai-workspace tmpfs defaults,noatime,size=512M,mode=0750 0 0

sudo mount /var/lib/ai-workspace
```

### 3. Конфигурация

```bash
cp .env.example .env
# Отредактировать .env:
#   ZAI_API_KEY=...
#   MATTERMOST_BOT_TOKEN=...
#   MATTERMOST_TEAM_NAME=...
```

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

#### 4c. Настроить Outgoing Webhook (запуск пайплайна)

1. **Integrations → Outgoing Webhooks → Add Outgoing Webhook**
   - Title: `AI Engineering Trigger`
   - Channel: `ai-engineering-factory`
   - Trigger When: `Words start with a message`
   - Trigger Word: `ai_lead`
   - Callback URLs: `http://172.17.0.1:8000/webhook`
   - Content Type: `application/json`

> **Почему `172.17.0.1`?** — это IP интерфейса docker0 bridge.
> Mattermost работает в Docker и обращается к API-шлюзу хоста через этот IP.
> Если Mattermost НЕ в Docker (работает напрямую на хосте), используйте `http://127.0.0.1:8000/webhook`.

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
ZAI_API_KEY=... MATTERMOST_BOT_TOKEN=... MATTERMOST_TEAM_NAME=ai-engineering-factory \
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Использование

### Запуск задачи

В канале `ai-engineering-factory` отправить сообщение, начинающееся с `ai_lead`:

```
ai_lead Напиши Python-скрипт для конвертации CSV в JSON с поддержкой вложенных ключей
```

### Что происходит

1. **Outgoing Webhook** отправляет текст в FastAPI
2. **FastAPI** создаёт workspace `thread_{post_id}` и запускает граф
3. **Stage 1 (Researcher)** — анализирует задачу → пост в `#ai-researcher`
4. **Stage 2 (Programmer)** — пишет код → пост в `#ai-programmer`
5. **Stage 3 (Debugger)** — проверяет код → пост в `#ai-debugger`
   - Если ошибки: возврат на Stage 2 (до 3 итераций)
   - Если чисто: передача валидатору
6. **Stage 4 (Validator)** — сверяет с планом → пост в `#ai-validator`
7. **Stage 5 (Reporter)** — финальный отчёт → пост в `#ai-reporter` + результат в исходный тред

### Наблюдение за агентами

Пользователь может открыть параллельно каналы:

- `#ai-researcher` — аналитика и план
- `#ai-programmer` — код и исправления
- `#ai-debugger` — результаты отладки
- `#ai-validator` — финальная проверка
- `#ai-reporter` — итоговый отчёт
- `#ai-control` — системные решения (loop, guardrail)

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

| Stage | Агент | Модель | Temperature | Что делает |
|-------|-------|--------|-------------|------------|
| 1 | Researcher | glm-5.2 | 0.3 | Анализирует задачу, составляет план |
| 2 | Programmer | glm-5.2 | 0.0 | Пишет/исправляет код |
| 3 | Debugger | glm-5.2 (with_structured_output) | 0.0 | Проверяет на ошибки, возвращает JSON |
| 4 | Validator | glm-5.2 | 0.0 | Сверяет с планом (не перезаписывает код!) |
| 5 | Reporter | — | — | Формирует финальный отчёт |

---

## Конфигурация (.env)

| Переменная | Обязательная | По умолчанию | Описание |
|-----------|-------------|-------------|----------|
| `ZAI_API_KEY` | Да | — | API ключ Z.AI |
| `MATTERMOST_BOT_TOKEN` | Да | — | Токен бота Mattermost |
| `MATTERMOST_TEAM_NAME` | Да | `ai-engineering-factory` | Название команды Mattermost |
| `MATTERMOST_URL` | Нет | `http://127.0.0.1:8065` | Базовый URL Mattermost |
| `ZAI_BASE_URL` | Нет | `https://api.z.ai/api/coding/paas/v4` | Эндпоинт Z.AI Coding |
| `LLM_CALL_TIMEOUT` | Нет | `180` | Таймаут LLM-вызова (сек) |

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
curl http://172.17.0.1:8000/webhook -X POST -H "Content-Type: application/json" \
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

---

## Troubleshooting

**"Канал ai-researcher не найден"** — бот не добавлен в канал или handle не совпадает.
→ `/invite @ai-orchestrator` в каждом канале.

**"plan.md пуст"** — webhook не передал текст или `initial_task` пустой.
→ Проверить формат сообщения: `ai_lead <текст задачи>`.

**"LLM call timed out"** — Z.AI отвещает дольше 180 секунд.
→ Увеличить `LLM_CALL_TIMEOUT` в `.env`.

**"Stage X FAILED"** — смотреть `journalctl -u ai-orchestrator -f`.
