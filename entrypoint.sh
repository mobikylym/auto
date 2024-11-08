#!/bin/bash

# Ссылка на репозиторий по умолчанию
REPO_URL="${REPO_URL:-https://github.com/mobikylym/auto.git}"

# Проверяем, пустая ли директория /project
if [ -z "$(ls -A /project)" ]; then
    echo "Cloning project repository from $REPO_URL..."
    git clone "$REPO_URL" /project
fi

ls -la /project

# Проверяем, установлены ли зависимости
if [ ! -f "/opt/venv/bin/pytest" ]; then
    echo "Installing dependencies..."
    /opt/venv/bin/pip install --no-cache-dir -r /project/requirements.txt
fi

# Запускаем указанную команду
exec "$@"