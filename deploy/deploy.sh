#!/bin/bash
# RentRadar — Деплой с локальной машины
# Пушит в GitHub, затем обновляет сервер через git pull
set -euo pipefail

SERVER="root@85.193.82.62"

echo "=== RentRadar: деплой ==="

# 1. Push в GitHub
echo "[1/2] Push в GitHub..."
git push origin main

# 2. Обновить сервер
echo "[2/2] Обновление сервера..."
ssh "$SERVER" "cd /opt/rentradar && git pull && bash deploy/update.sh"

echo "=== Деплой завершён ==="
echo "https://rentradar.gesolutions.ru"
