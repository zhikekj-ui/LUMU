---
name: server-ops
description: 本机服务器运维操作规范（重启服务、查日志、改配置的标准流程）
triggers: 重启,部署,日志,nginx,systemd,服务挂了
always: false
---
# 服务器运维守则

1. 任何变更前先确认服务状态：systemctl status lumu-agent
2. 改配置前先备份原文件（cp xx xx.bak.$(date +%s)）
3. 重启服务用 systemctl restart lumu-agent，禁止 kill -9 主进程
4. 重启后必须验证：curl http://127.0.0.1:8000/health 返回 ok
5. 查日志：journalctl -u lumu-agent -n 100 --no-pager
6. 遇到端口占用：用 ss -tlnp 找 PID，按 PID 处理，禁止 pkill -f
