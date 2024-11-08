FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /project

RUN apt-get update && apt-get install -y \
    python3-dev \
    python3-venv \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    git && \
    python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]

CMD ["pytest"]
