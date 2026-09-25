#!/usr/bin/env bash
# 清空 AI 测试平台业务数据；保留 AI 模型配置、路由、初始化账号和 embedding 缓存。
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ASSUME_YES=0
DRY_RUN=0
CREATE_BACKUP=1

usage() {
  cat <<'EOF'
用法：
  ./cleanup-test-data.sh              # 交互确认、自动备份后清理
  ./cleanup-test-data.sh --yes        # 无交互执行（适合运维脚本）
  ./cleanup-test-data.sh --dry-run    # 仅查看将被清理的数据
  ./cleanup-test-data.sh --yes --no-backup

保留：AI 模型配置、模型路由、初始化账号、数据库迁移版本、embedding 模型缓存。
清理：其余数据库业务数据、Redis、Celery 队列、MinIO 对象及 data 下业务文件。
EOF
}

while (($#)); do
  case "$1" in
    --yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --no-backup) CREATE_BACKUP=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
elif sudo -n docker info >/dev/null 2>&1; then
  DOCKER=(sudo -n docker)
else
  echo "无法访问 Docker。请使用具有 Docker 权限的账号，或配置 sudo -n docker。" >&2
  exit 1
fi
COMPOSE=("${DOCKER[@]}" compose)

if ((DRY_RUN)); then
  "${COMPOSE[@]}" run --rm --no-deps backend \
    python scripts/cleanup_test_data.py --dry-run
  exit 0
fi

if ((!ASSUME_YES)); then
  echo "即将永久删除平台全部业务/测试数据。AI 模型配置、路由和初始化账号会保留。"
  read -r -p "请输入 CLEAN 确认继续: " answer
  if [[ "$answer" != "CLEAN" ]]; then
    echo "已取消。"
    exit 0
  fi
fi

if ((CREATE_BACKUP)); then
  BACKUP_DIR="${AITP_BACKUP_DIR:-${HOME}/aitp-backups}"
  mkdir -p "$BACKUP_DIR"
  timestamp="$(date +%Y%m%d-%H%M%S)"
  backup_file="$BACKUP_DIR/before-cleanup-$timestamp.sql.gz"
  db_user="$("${DOCKER[@]}" exec aitp-postgres printenv POSTGRES_USER)"
  db_name="$("${DOCKER[@]}" exec aitp-postgres printenv POSTGRES_DB)"
  "${DOCKER[@]}" exec aitp-postgres pg_dump -U "$db_user" -d "$db_name" \
    | gzip -c > "$backup_file"
  test -s "$backup_file"
  echo "数据库备份已生成: $backup_file"
fi

services_stopped=0
restart_services() {
  if ((services_stopped)); then
    "${COMPOSE[@]}" up -d backend celery-worker celery-beat
  fi
}
trap restart_services EXIT

"${COMPOSE[@]}" stop backend celery-worker celery-beat
services_stopped=1

# 停止消费者后清空尚未执行的任务，避免服务恢复时消费清理前遗留消息。
for queue in celery execution; do
  "${DOCKER[@]}" exec aitp-rabbitmq rabbitmqctl purge_queue "$queue" >/dev/null 2>&1 || true
done

"${COMPOSE[@]}" run --rm --no-deps backend \
  python scripts/cleanup_test_data.py --yes

restart_services
services_stopped=0
trap - EXIT

echo "平台测试数据已清理，应用服务已恢复。"
