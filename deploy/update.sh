#!/bin/bash
# RentRadar — Обновление после git pull
# Запуск на сервере: cd /opt/rentradar && git pull && bash deploy/update.sh
set -euo pipefail

echo "=== RentRadar: обновление ==="

# Дашборд
cp dashboard/index.html /var/www/rentradar/

# Systemd (если изменились)
cp deploy/rentradar.service /etc/systemd/system/
cp deploy/rentradar.timer /etc/systemd/system/
systemctl daemon-reload

# Nginx (если изменился)
cp deploy/nginx.conf /etc/nginx/sites-enabled/rentradar.gesolutions.ru
nginx -t && systemctl reload nginx

echo "=== Готово ==="
