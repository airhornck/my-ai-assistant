# 热重载模式启动脚本（Windows PowerShell）
#
# 使用方式：
#   .\scripts\hotreload.ps1 up      # 启动服务
#   .\scripts\hotreload.ps1 down    # 停止服务
#   .\scripts\hotreload.ps1 build   # 重新构建镜像
#   .\scripts\hotreload.ps1 logs    # 查看日志
#   .\scripts\hotreload.ps1 restart # 重启服务

param(
    [Parameter(Position=0)]
    [string]$Command = "up"
)

$ComposeFile = "docker-compose.hotreload.yml"
$EnvFile = ".env.prod"

function Check-EnvFile {
    if (-not (Test-Path $EnvFile)) {
        Write-Host "❌ 错误：找不到环境配置文件 $EnvFile" -ForegroundColor Red
        Write-Host "请先创建 $EnvFile 文件，可以参考 .env.prod.example"
        exit 1
    }
}

function Show-Help {
    @"
热重载模式管理脚本

使用方法: .\scripts\hotreload.ps1 [命令]

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
  - 确保已创建 $EnvFile 文件
  - 首次运行会自动构建镜像

"@
}

function Start-HotReload {
    Check-EnvFile
    Write-Host "🚀 启动热重载模式..." -ForegroundColor Green
    Write-Host "   配置文件: $EnvFile"
    Write-Host "   Compose文件: $ComposeFile"
    Write-Host ""
    Write-Host "💡 提示：代码修改后会自动热重载，无需重启容器！" -ForegroundColor Cyan
    Write-Host ""
    docker compose --env-file "$EnvFile" -f "$ComposeFile" up -d
    Write-Host ""
    Write-Host "✅ 服务已启动！" -ForegroundColor Green
    Write-Host "   应用访问: http://localhost:8000"
    Write-Host "   API文档:  http://localhost:8000/docs"
    Write-Host "   健康检查: http://localhost:8000/health"
    Write-Host ""
    Write-Host "📊 监控面板："
    Write-Host "   Prometheus: http://localhost:9090"
    Write-Host "   Grafana:    http://localhost:3000 (admin/admin)"
    Write-Host ""
    Write-Host "📝 查看日志：.\scripts\hotreload.ps1 logs"
}

function Stop-HotReload {
    Write-Host "🛑 停止热重载模式服务..." -ForegroundColor Yellow
    docker compose -f "$ComposeFile" down
    Write-Host "✅ 服务已停止" -ForegroundColor Green
}

function Build-Image {
    Check-EnvFile
    Write-Host "🔨 重新构建镜像..." -ForegroundColor Blue
    docker compose --env-file "$EnvFile" -f "$ComposeFile" build --no-cache
    Write-Host "✅ 镜像构建完成" -ForegroundColor Green
}

function Show-Logs {
    Write-Host "📋 查看应用日志（按 Ctrl+C 退出）..." -ForegroundColor Blue
    Write-Host "💡 你会看到 'Reloading...' 提示表示热重载正在工作" -ForegroundColor Cyan
    Write-Host ""
    docker compose -f "$ComposeFile" logs -f app
}

function Restart-Service {
    Write-Host "🔄 重启服务..." -ForegroundColor Blue
    docker compose -f "$ComposeFile" restart
    Write-Host "✅ 服务已重启" -ForegroundColor Green
}

function Enter-Shell {
    Write-Host "🐚 进入应用容器命令行..." -ForegroundColor Blue
    docker compose -f "$ComposeFile" exec app bash
}

function Show-Status {
    Write-Host "📊 服务运行状态：" -ForegroundColor Blue
    docker compose -f "$ComposeFile" ps
}

# 主逻辑
switch ($Command.ToLower()) {
    "up" { Start-HotReload }
    "down" { Stop-HotReload }
    "build" { Build-Image }
    "logs" { Show-Logs }
    "restart" { Restart-Service }
    "shell" { Enter-Shell }
    "status" { Show-Status }
    "help" { Show-Help }
    "--help" { Show-Help }
    "-h" { Show-Help }
    default {
        Write-Host "❌ 未知命令: $Command" -ForegroundColor Red
        Show-Help
        exit 1
    }
}
