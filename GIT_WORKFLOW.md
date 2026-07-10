# Git Workflow — AI Orchestrator

## Содержание

1. [Выгрузка проекта на GitHub (локальный ПК → GitHub)](#1-выгрузка-проекта-на-github)
2. [Обновление проекта на сервере Ubuntu (GitHub → сервер)](#2-обновление-проекта-на-сервере-ubuntu)

---

# 1. Выгрузка проекта на GitHub (локальный ПК → GitHub)

## Предварительные требования

- Установленный Git на локальном ПК: `git --version`
- Аккаунт на [GitHub.com](https://github.com)
- SSH-ключ добавлен в GitHub (или Personal Access Token)
  - [Гайд по SSH](https://docs.github.com/en/authentication/connecting-to-github-with-ssh)

---

## Пошаговая инструкция

### 1.1. Создать пустой репозиторий на GitHub

1. Зайти на https://github.com → **New repository**
2. **Repository name:** `mattermost-ai-orchestrator`
3. **Description:** `Multi-agent AI orchestrator for Mattermost with LangGraph and Z.AI`
4. **Visibility:** `Private` (рекомендуется — содержит конфигурацию интеграций)
5. **НЕ отмечать** "Add a README", "Add .gitignore", "Add a license" (они уже есть в проекте)
6. Нажать **Create repository**

Скопировать URL репозитория:
- SSH: `git@github.com:ВАШ_АККАУНТ/mattermost-ai-orchestrator.git`
- HTTPS: `https://github.com/ВАШ_АККАУНТ/mattermost-ai-orchestrator.git`

### 1.2. Настроить remote в локальном репозитории

```bash
cd C:\Users\User\Desktop\MyProects\MattermostBots
```

Проверить текущий remote:

```bash
git remote -v
```

Если remote указывает на placeholder — обновить:

```bash
git remote set-url origin git@github.com:ВАШ_АККАУНТ/mattermost-ai-orchestrator.git
```

Если remote не настроен — добавить:

```bash
git remote add origin git@github.com:ВАШ_АККАУНТ/mattermost-ai-orchestrator.git
```

### 1.3. Закоммитить текущие изменения

```bash
git add .
```

> `.env` не попадёт в коммит — он в `.gitignore`.
> Если `.env` всё равно отображается в `git status` — проверить `.gitignore`.

```bash
git commit -m "Full project: multi-project AI orchestrator with slash commands, per-agent LLM, file generation"
```

### 1.4. Запушить на GitHub

```bash
git push -u origin master
```

При первом push может потребоваться:
- **HTTPS:** окно входа в GitHub (браузер или token)
- **SSH:** подтверждение fingerprint сервера

### 1.5. Проверка

```bash
git log --oneline -3
git remote -v
```

**Что в репозитории:**
| Файл | Статус |
|------|--------|
| `main.py`, `graph.py`, `projects.py` | ✅ |
| `requirements.txt` | ✅ |
| `.env.example` | ✅ (шаблон, без секретов) |
| `ai-orchestrator.service` | ✅ |
| `default-prompts/*.md` | ✅ |
| `README.md`, `GIT_WORKFLOW.md` | ✅ |
| `.gitignore` | ✅ |
| `.env` | ❌ (в .gitignore) |
| `venv/`, `__pycache__/` | ❌ (в .gitignore) |

---

# 2. Обновление проекта на сервере Ubuntu (GitHub → сервер)

## Ситуация

Проект уже работает на сервере: файлы в `/opt/ai-orchestrator/`, запущен через systemd.
Вы внесли изменения в код на локальном ПК, запушили в GitHub.
Теперь нужно обновить код на сервере.

---

## Пошаговая инструкция

### 2.1. Первый раз: клонировать репозиторий на сервер

**Это нужно сделать только один раз — при первой настройке.**

```bash
# Перейти в родительскую директорию
cd /opt

# Убедиться, что старая версия сохранена
sudo mv ai-orchestrator ai-orchestrator-backup

# Клонировать репозиторий
sudo git clone git@github.com:ВАШ_АККАУНТ/mattermost-ai-orchestrator.git

# Назначить владельца
sudo chown -R ai-orchestrator:ai-orchestrator /opt/ai-orchestrator
```

**Настроить .env (секреты не в репозитории):**

```bash
# Восстановить .env из бэкапа (содержит ZAI_API_KEY, MATTERMOST_BOT_TOKEN и т.д.)
sudo cp /opt/ai-orchestrator-backup/.env /opt/ai-orchestrator/.env
sudo chmod 600 /opt/ai-orchestrator/.env

# Либо создать заново из шаблона
sudo cp /opt/ai-orchestrator/.env.example /opt/ai-orchestrator/.env
sudo nano /opt/ai-orchestrator/.env   # вставить секреты
```

**Настроить виртуальное окружение:**

```bash
cd /opt/ai-orchestrator
sudo -u ai-orchestrator python3 -m venv venv
sudo -u ai-orchestrator ./venv/bin/pip install --no-cache-dir -r requirements.txt
```

**Настроить default-prompts:**

```bash
# Скопировать дефолтные промты (если папка новая)
sudo mkdir -p /opt/ai-orchestrator/default-prompts
sudo cp -r /opt/ai-orchestrator/default-prompts/* /opt/ai-orchestrator/default-prompts/
sudo chown -R ai-orchestrator:ai-orchestrator /opt/ai-orchestrator/default-prompts/
```

**Настроить и запустить systemd:**

```bash
sudo cp /opt/ai-orchestrator/ai-orchestrator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-orchestrator
sudo systemctl start ai-orchestrator
sudo systemctl status ai-orchestrator
```

---

### 2.2. Обычное обновление (pull изменений)

Выполнять каждый раз, когда нужно обновить код на сервере.

**Шаг 1 — Подключиться к серверу**

```bash
ssh user@your-server-ip
```

**Шаг 2 — Остановить сервис**

```bash
sudo systemctl stop ai-orchestrator
```

**Шаг 3 — Скачать изменения из GitHub**

```bash
cd /opt/ai-orchestrator
sudo -u ai-orchestrator git pull origin master
```

Если возникли конфликты:

```bash
# Посмотреть конфликтные файлы
git status

# Отменить локальные изменения (если они не нужны)
git checkout --their <file>

# Или отложить локальные изменения
git stash
git pull
git stash pop
```

**Шаг 4 — Обновить зависимости (если requirements.txt изменился)**

```bash
sudo -u ai-orchestrator ./venv/bin/pip install --no-cache-dir -r requirements.txt
```

**Шаг 5 — Обновить default-prompts (если папка изменилась)**

```bash
sudo cp -r /opt/ai-orchestrator/default-prompts/* /opt/ai-orchestrator/default-prompts/
```

**Шаг 6 — Обновить systemd-юнит (если service файл изменился)**

```bash
sudo cp /opt/ai-orchestrator/ai-orchestrator.service /etc/systemd/system/
sudo systemctl daemon-reload
```

**Шаг 7 — Запустить сервис**

```bash
sudo systemctl start ai-orchestrator
sudo systemctl status ai-orchestrator  # проверить, что работает
```

**Шаг 8 — Проверить логи**

```bash
journalctl -u ai-orchestrator -n 20 --no-pager
```

---

## Быстрый скрипт обновления (одной командой)

Сохранить на сервере как `/usr/local/bin/update-ai-orchestrator.sh`:

```bash
#!/bin/bash
set -e

echo "=== Updating AI Orchestrator ==="
sudo systemctl stop ai-orchestrator

cd /opt/ai-orchestrator
sudo -u ai-orchestrator git pull origin master

if git diff HEAD@{1} --name-only | grep -q requirements.txt; then
    echo "Requirements changed — reinstalling dependencies..."
    sudo -u ai-orchestrator ./venv/bin/pip install --no-cache-dir -r requirements.txt
fi

if git diff HEAD@{1} --name-only | grep -q ai-orchestrator.service; then
    echo "Service file changed — reloading systemd..."
    sudo cp ai-orchestrator.service /etc/systemd/system/
    sudo systemctl daemon-reload
fi

sudo systemctl start ai-orchestrator
echo "=== Update complete ==="
sudo systemctl status ai-orchestrator --no-pager -l
```

Запуск:

```bash
sudo chmod +x /usr/local/bin/update-ai-orchestrator.sh
sudo /usr/local/bin/update-ai-orchestrator.sh
```

---

## Важные замечания

| Компонент | Где хранится | Попадает в GitHub? |
|-----------|-------------|-------------------|
| Исходный код | `/opt/ai-orchestrator/` | ✅ все `.py`, `.md`, `.txt` |
| `.env` | `/opt/ai-orchestrator/.env` | ❌ (секреты) |
| `venv/` | `/opt/ai-orchestrator/venv/` | ❌ (тяжёлый, пересоздаётся) |
| `__pycache__/` | в папках проекта | ❌ (в .gitignore) |
| Логи | `journalctl` | ❌ |
| Рабочие проекты | `/var/lib/ai-workspace/projects/` | ❌ (данные пользователей) |
| systemd unit | `/etc/systemd/system/ai-orchestrator.service` | ❌ (копируется руками) |
| default-prompts | `/opt/ai-orchestrator/default-prompts/` | ✅ |
