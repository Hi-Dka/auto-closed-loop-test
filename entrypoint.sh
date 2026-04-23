#!/bin/bash
set -e

echo "正在启动容器配置..."

ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

echo "正在通过 Supervisor 启动 Python 监控和 Rust 程序..."

exec /usr/bin/supervisord -c /app/supervisord.conf