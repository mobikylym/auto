#!/bin/bash

REPO_URL="${REPO_URL:-https://github.com/mobikylym/auto.git}"

if [ -z "$(ls -A /project | grep -v allure-results)" ]; then
    echo "Cloning project repository from $REPO_URL..."
    git clone "$REPO_URL" /tmp/repo_clone

    echo "Moving project files to /project..."
    mv /tmp/repo_clone/* /project/
    mv /tmp/repo_clone/.[^.]* /project/
    rm -rf /tmp/repo_clone

    if [ ! -f "/opt/venv/bin/pytest" ]; then
      echo "Installing dependencies..."
      /opt/venv/bin/pip install --no-cache-dir -r /project/requirements.txt
    fi
else
    echo "Checking for updates in the repository..."
    cd /project
    git fetch origin

    if [ "$(git rev-parse HEAD)" != "$(git rev-parse @{u})" ]; then
        echo "Updates found. Pulling latest changes..."
        git pull

        echo "Reinstalling dependencies..."
        /opt/venv/bin/pip install --no-cache-dir -r /project/requirements.txt
    else
        echo "Repository is already up to date."
    fi
fi

exec "$@"