#!/bin/bash
# RentRadar — Установка на VPS из GitHub
# Запуск: ssh root@85.193.82.62 'bash -s' < deploy/install.sh
# Или: скопировать на сервер и запустить
set -euo pipefail

REPO="https://github.com/gesolutions/rentradar.git"
APP_DIR="/opt/rentradar"
WEB_DIR="/var/www/rentradar"

echo "=== RentRadar: установка ==="

# 1. Клонировать репозиторий
echo "[1/7] Клонирование из GitHub..."
mkdir -p "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR" && git pull
else
    git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

# 2. Структура
echo "[2/7] Создание директорий..."
mkdir -p "$APP_DIR/data" "$APP_DIR/logs"
mkdir -p "$WEB_DIR/data"
chown -R deploy:deploy "$APP_DIR"
chown -R deploy:deploy "$WEB_DIR"

# 3. Виртуальное окружение + зависимости
echo "[3/7] Python venv + зависимости..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install httpx playwright apscheduler
playwright install chromium --with-deps

# 4. Дашборд -> nginx root
echo "[4/7] Копирование дашборда..."
cp dashboard/index.html "$WEB_DIR/"

# 5. Systemd
echo "[5/7] Настройка systemd..."
cp deploy/rentradar.service /etc/systemd/system/
cp deploy/rentradar.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable rentradar.timer
systemctl start rentradar.timer
echo "Timer status:"
systemctl status rentradar.timer --no-pager || true

# 6. Nginx
echo "[6/7] Настройка nginx..."
cp deploy/nginx.conf /etc/nginx/sites-enabled/rentradar.gesolutions.ru
nginx -t
systemctl reload nginx

# 7. SSL
echo "[7/7] SSL сертификат..."
certbot --nginx -d rentradar.gesolutions.ru --non-interactive --agree-tos --email admin@gesolutions.ru || {
    echo "ВНИМАНИЕ: certbot не смог получить сертификат."
    echo "Проверьте A-запись rentradar.gesolutions.ru -> 85.193.82.62"
}

echo ""
echo "=== RentRadar: установка завершена ==="
echo "Дашборд: https://rentradar.gesolutions.ru"
echo "Первый запуск: systemctl start rentradar.service"
echo "Обновление: cd $APP_DIR && git pull && bash deploy/update.sh"
