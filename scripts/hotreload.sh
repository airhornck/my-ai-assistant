#!/bin/bash
# 热重载模式启动脚本（Linux/macOS）
#
# 使用方式：
#   ./scripts/hotreload.sh up      # 启动服务
#   ./scripts/hotreload.sh down    # 停止服务
#   ./scripts/hotreload.sh build   # 重新构建镜像
#   ./scripts/hotreload.sh logs    # 查看日志
#   ./scripts/hotreload.sh restart # 重启服务

set -e

COMPOSE_FILE="docker-compose.hotreload.yml"
ENV_FILE=".env.prod"

check_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        echo "❌ 错误：找不到环境配置文件 $ENV_FILE"
        echo "请先创建 $ENV_FILE 文件，可以参考 .env.prod.example"
        exit 1
    fi
}

show_help() {
    cat << EOF
热重载模式管理脚本

使用方法: $0 [命令]

命令:
  up       启动热重载模式服务（首次会自动构建镜像）
  down     停止并移除所有服务
  build    重新构建 Docker 镜像
  logs     查看应用日志（带热重载提示）
  restart  重启服务
  shell    进入应用容器命令行（用于调试）
  status   查看服务运行状态

特点：
  - 代码修改后自动热重载，无需重启容器
  - 代码通过 volume 挂载，不是打包进镜像
  - 适合开发和快速迭代

注意：
  - 确保已创建 $ENV_FILE 文件
  - 首次运行会自动构建镜像

EOF
}

cmd_up() {
    check_env_file
    echo "🚀 启动热重载模式..."
    echo "   配置文件: $ENV_FILE"
    echo "   Compose文件: $COMPOSE_FILE"
    echo ""
    echo "💡 提示：代码修改后会自动热重载，无需重启容器！"
    echo ""
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
    echo ""
    echo "✅ 服务已启动！"
    echo "   应用访问: http://localhost:8000"
    echo "   API文档:  http://localhost:8000/docs"
    echo "   健康检查: http://localhost:8000/health"
    echo ""
    echo "📊 监控面板："
    echo "   Prometheus: http://localhost:9090"
    echo "   Grafana:    http://localhost:3000 (admin/admin)"
    echo ""
    echo "📝 查看日志：$0 logs"
}

cmd_down() {
    echo "🛑 停止热重载模式服务..."
    docker compose -f "$COMPOSE_FILE" down
    echo "✅ 服务已停止"
}

cmd_build() {
    check_env_file
    echo "🔨 重新构建镜像..."
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build --no-cache
    echo "✅ 镜像构建完成"
}

cmd_logs() {
    echo "📋 查看应用日志（按 Ctrl+C 退出）..."
    echo "💡 你会看到 'Reloading...' 提示表示热重载正在工作"
    echo ""
    docker compose -f "$COMPOSE_FILE" logs -f app
}

cmd_restart() {
    echo "🔄 重启服务..."
    docker compose -f "$COMPOSE_FILE" restart
    echo "✅ 服务已重启"
}

cmd_shell() {
    echo "🐚 进入应用容器命令行..."
    docker compose -f "$COMPOSE_FILE" exec app bash
}

cmd_status() {
    echo "📊 服务运行状态："
    docker compose -f "$COMPOSE_FILE" ps
}

# 主逻辑
case "${1:-up}" in
    up)
        cmd_up
        ;;
    down)
        cmd_down
        ;;
    build)
        cmd_build
        ;;
    logs)
        cmd_logs
        ;;
    restart)
        cmd_restart
        ;;
    shell)
        cmd_shell
        ;;
    status)
        cmd_status
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo "❌ 未知命令: $1"
        show_help
        exit 1
        ;;
esac
