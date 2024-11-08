FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /project

# Устанавливаем системные зависимости и создаем виртуальное окружение
RUN apt-get update && apt-get install -y \
    python3-dev \
    python3-venv \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    git && \
    python3 -m venv /opt/venv

# Добавляем виртуальное окружение в PATH
ENV PATH="/opt/venv/bin:$PATH"

# Копируем скрипт запуска
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Устанавливаем ENTRYPOINT для выполнения команд при создании контейнера и запуске
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

# Команда по умолчанию для запуска тестов
CMD ["pytest"]