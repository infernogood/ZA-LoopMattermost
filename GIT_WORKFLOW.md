# Git Workflow — AI Orchestrator

## Схема

```
Локальный ПК (Windows/Linux)
│  git push
▼
GitHub (infernogood/ZA-LoopMattermost)
│  git pull
▼
Сервер Ubuntu 22.04 (/opt/ai-orchestrator/)
```

---

## 1. Первый пуш с локального ПК на GitHub

### 1.1 Проверить текущий remote

```bash
cd C:\Users\User\Desktop\MyProects\MattermostBots
git remote -v
# -> origin  https://github.com/YOUR_USERNAME/mattermost-ai-orchestrator.git (fetch)
# -> origin  https://github.com/YOUR_USERNAME/mattermost-ai-orchestrator.git (push)
```

Remote указывает на placeholder — нужно сменить на ваш репозиторий.

### 1.2 Сменить remote на ваш GitHub

```bash
git remote set-url origin git@github.com:infernogood/ZA-LoopMattermost.git
git remote -v
# -> origin  git@github.com:infernogood/ZA-LoopMattermost.git (fetch)
# -> origin  git@github.com:infernogood/ZA-LoopMattermost.git (push)
```

### 1.3 Проверить, что SSH-ключ добавлен в GitHub

```bash
ssh -T git@github.com
# -> Hi infernogood! You've successfully authenticated...
```

Если нет — добавить публичный ключ: `https://github.com/settings/keys`

### 1.4 Проверить .gitignore

Открыть `.gitignore` — убедиться, что там есть:

```
.env
venv/
.venv/
__pycache__/
*.tmp
```

### 1.5 Просмотреть что попадёт в коммит

```bash
git status
```

Должны быть:
- `main.py`
- `graph.py`
- `projects.py`
- `requirements.txt`
- `.env.example`
- `.gitignore`
- `ai-orchestrator.service`
- `default-prompts/`
- `README.md`
- `GIT_WORKFLOW.md`

**Не должны** попасть:
- `.env` (секреты)
- `venv/` (окружение)
- `__pycache__/`
- `*.tmp`

### 1.6 Создать коммит и запушить

```bash
git add .
git commit -m "Deploy-ready: multi-project AI orchestrator with slash commands, per-agent LLM, file generation"
git push -u origin main
```

Если ветка называется `master` вместо `main`:

```bash
git branch -M main
git push -u origin main
```

---

## 2. Клонирование на сервер Ubuntu 22.04 (при первом развёртывании)

### 2.1 Установить git на сервере

```bash
sudo apt update
sudo apt install git -y
```

### 2.2 Добавить SSH-ключ сервера в GitHub

На сервере:

```bash
ssh-keygen -t ed25519 -C "ubuntu-server"
cat ~/.ssh/id_ed25519.pub
```

Скопировать вывод. Перейти на GitHub → **Settings → SSH and GPG keys → New SSH key** → вставить ключ.

### 2.3 Сделать бэкап текущей версии (если есть)

```bash
sudo cp -r /opt/ai-orchestrator /opt/ai-orchestrator.backup-$(date +%Y%m%d_%H%M%S)
```

### 2.4 Удалить старые файлы проекта (кроме .env, venv, workspace)

```bash
cd /opt/ai-orchestrator
sudo rm -f main.py graph.py projects.py requirements.txt .env.example
sudo rm -rf default-prompts/
```

### 2.5 Клонировать репозиторий во временную папку

```bash
git clone git@github.com:infernogood/ZA-LoopMattermost.git /tmp/za-loop-mattermost
```

### 2.6 Скопировать новые файлы на место

```bash
sudo cp /tmp/za-loop-mattermost/main.py /opt/ai-orchestrator/
sudo cp /tmp/za-loop-mattermost/graph.py /opt/ai-orchestrator/
sudo cp /tmp/za-loop-mattermost/projects.py /opt/ai-orchestrator/
sudo cp /tmp/za-loop-mattermost/requirements.txt /opt/ai-orchestrator/
sudo cp /tmp/za-loop-mattermost/.env.example /opt/ai-orchestrator/
sudo cp /tmp/za-loop-mattermost/ai-orchestrator.service /opt/ai-orchestrator/
sudo cp /tmp/za-loop-mattermost/README.md /opt/ai-orchestrator/
sudo cp -r /tmp/za-loop-mattermost/default-prompts /opt/ai-orchestrator/
```

### 2.7 Удалить временную папку

```bash
rm -rf /tmp/za-loop-mattermost
```

### 2.8 Обновить зависимости (если изменились)

```bash
cd /opt/ai-orchestrator
sudo ./venv/bin/pip install --no-cache-dir -r requirements.txt
```

### 2.9 Перезапустить сервис

```bash
sudo systemctl daemon-reload
sudo systemctl restart ai-orchestrator
sudo systemctl status ai-orchestrator
```

---

## 3. Обновление с GitHub на сервер (последующие разы)

```bash
# 1. Склонировать свежую версию
git clone git@github.com:infernogood/ZA-LoopMattermost.git /tmp/za-update

# 2. Наложить файлы (только те, что изменились)
cd /opt/ai-orchestrator
sudo cp /tmp/za-update/main.py .
sudo cp /tmp/za-update/graph.py .
sudo cp /tmp/za-update/projects.py .
sudo cp /tmp/za-update/requirements.txt .
sudo cp -r /tmp/za-update/default-prompts .

# 3. Очистка
rm -rf /tmp/za-update

# 4. Зависимости (если изменились)
sudo ./venv/bin/pip install --no-cache-dir -r requirements.txt

# 5. Перезапуск
sudo systemctl restart ai-orchestrator
sudo systemctl status ai-orchestrator
```

---

## 4. Автоматизация обновления (скрипт deploy.sh)

Для ускорения можно создать скрипт `/opt/ai-orchestrator/deploy.sh`:

```bash
#!/bin/bash
set -e

TMP_DIR=$(mktemp -d)
git clone git@github.com:infernogood/ZA-LoopMattermost.git "$TMP_DIR"

cd /opt/ai-orchestrator

sudo cp "$TMP_DIR/main.py" .
sudo cp "$TMP_DIR/graph.py" .
sudo cp "$TMP_DIR/projects.py" .
sudo cp "$TMP_DIR/requirements.txt" .
sudo cp -r "$TMP_DIR/default-prompts" .

rm -rf "$TMP_DIR"

sudo ./venv/bin/pip install --no-cache-dir -r requirements.txt
sudo systemctl restart ai-orchestrator
sudo systemctl status ai-orchestrator --no-pager
```

```bash
sudo chmod +x /opt/ai-orchestrator/deploy.sh
sudo ./opt/ai-orchestrator/deploy.sh
```

---

## Важно

| Файл | В git? | На сервере | Комментарий |
|------|--------|------------|-------------|
| `.env` | ❌ .gitignore | `/opt/ai-orchestrator/.env` | Секреты — не коммитить |
| `venv/` | ❌ .gitignore | `/opt/ai-orchestrator/venv/` | Создаётся при установке |
| `/var/lib/ai-workspace/` | ❌ | `/var/lib/ai-workspace/` | Данные проектов — бэкапить отдельно |
| `default-prompts/` | ✅ | Копируется | Можно кастомизировать на сервере, но при обновлении затрётся |
