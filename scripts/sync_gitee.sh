#!/usr/bin/env bash
# sync_gitee.sh —— 将 LUMU 主仓同步到 Gitee 镜像（国内开发者可达）
#
# 用法：
#   GITEE_USER=zhikekj-ui ./scripts/sync_gitee.sh
# 默认 Gitee 组织/用户名为 zhikekj-ui，可用环境变量覆盖。
#
# 一次性前置（仅需做一次）：
#   1) 在 Gitee 创建同名空仓库 LUMU（不要初始化 README / 不要勾选 .gitignore）
#   2) 将本机公钥（~/.ssh/id_ed25519.pub）加入 Gitee「设置 → SSH 公钥」
#
set -euo pipefail

GITEE_USER="${GITEE_USER:-zhikekj-ui}"
GITEE_REPO="${GITEE_REPO:-LUMU}"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
REMOTE="gitee"

if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "▶ 添加 gitee remote: git@gitee.com:${GITEE_USER}/${GITEE_REPO}.git"
  git remote add "$REMOTE" "git@gitee.com:${GITEE_USER}/${GITEE_REPO}.git"
else
  echo "▶ gitee remote 已存在: $(git remote get-url "$REMOTE")"
fi

echo "▶ 推送 ${BRANCH} → Gitee (${GITEE_USER}/${GITEE_REPO})"
git push "$REMOTE" "$BRANCH"

echo "✅ Gitee 同步完成: https://gitee.com/${GITEE_USER}/${GITEE_REPO}"
