#!/bin/bash
# Health check for LUMU Agent Framework
ISSUES=0

# Check systemd service
if ! systemctl is-active --quiet lumu-agent; then
    echo "[CRITICAL] lumu-agent service is not running"
    systemctl restart lumu-agent
    ISSUES=$((ISSUES+1))
fi

# Check HTTP health
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health)
if [ "$HTTP_CODE" != "200" ]; then
    echo "[WARNING] Health endpoint returned $HTTP_CODE"
    ISSUES=$((ISSUES+1))
fi

# Check PostgreSQL
if ! systemctl is-active --quiet postgresql; then
    echo "[CRITICAL] PostgreSQL is not running"
    systemctl start postgresql
    ISSUES=$((ISSUES+1))
fi

# Check Redis
if ! systemctl is-active --quiet redis-server; then
    echo "[CRITICAL] Redis is not running"
    systemctl start redis-server
    ISSUES=$((ISSUES+1))
fi

# Check disk space
DISK_USAGE=$(df -h / | awk 'NR==2{print $5}' | tr -d '%')
if [ "$DISK_USAGE" -gt 85 ]; then
    echo "[WARNING] Disk usage at ${DISK_USAGE}%"
fi

# Check memory
MEM_AVAIL=$(free -m | awk 'NR==2{print $7}')
if [ "$MEM_AVAIL" -lt 200 ]; then
    echo "[WARNING] Available memory: ${MEM_AVAIL}MB"
fi

if [ $ISSUES -eq 0 ]; then
    echo "[OK] All systems healthy"
fi

exit $ISSUES
