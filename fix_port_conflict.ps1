# 端口冲突修复脚本
# 解决 8000 端口被多个服务占用的问题

Write-Host "=== 端口冲突诊断与修复 ===" -ForegroundColor Cyan
Write-Host ""

# 1. 检查当前占用 8000 端口的进程
Write-Host "1. 检查 8000 端口占用情况..." -ForegroundColor Yellow
$connections = netstat -ano | Select-String ":8000.*LISTENING"

if ($connections) {
    Write-Host "   发现以下进程正在监听 8000 端口:" -ForegroundColor Red
    $connections | ForEach-Object { Write-Host "   $_" }
    
    # 提取 PID
    $pids = $connections | ForEach-Object {
        if ($_ -match '\s+(\d+)\s*$') {
            $matches[1]
        }
    } | Select-Object -Unique
    
    Write-Host ""
    Write-Host "   涉及的进程 ID: $($pids -join ', ')" -ForegroundColor Yellow
    
    # 获取进程详情
    foreach ($pid in $pids) {
        $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "   - PID $pid : $($process.ProcessName) - $($process.Path)" -ForegroundColor White
        }
    }
} else {
    Write-Host "   ✓ 8000 端口当前空闲" -ForegroundColor Green
}

Write-Host ""
Write-Host "2. 检查 Docker 容器状态..." -ForegroundColor Yellow
docker ps --filter publish=8000 --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

Write-Host ""
Write-Host "=== 建议操作 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "方案 A: 只使用 Docker 容器（推荐）" -ForegroundColor Green
Write-Host "  1. 如果你启动了 uvicorn，请在其终端按 Ctrl+C 停止"
Write-Host "  2. 确保 Docker 容器运行: docker start ai_assistant_app_prod"
Write-Host "  3. 等待 30 秒让容器完全启动"
Write-Host "  4. 运行: python frontend/app_enhanced.py"
Write-Host ""
Write-Host "方案 B: 只使用本地 uvicorn" -ForegroundColor Yellow
Write-Host "  1. 停止 Docker 容器: docker stop ai_assistant_app_prod"
Write-Host "  2. 在新终端运行: uvicorn main:app --reload"
Write-Host "  3. 在另一个终端运行: python frontend/app_enhanced.py"
Write-Host ""
Write-Host "⚠️  关键：不要同时运行 Docker 容器和 uvicorn！" -ForegroundColor Red
Write-Host ""

# 提供快捷操作
Write-Host "快捷操作选项:" -ForegroundColor Cyan
Write-Host "  [A] 停止所有 Docker 容器（保留开发数据库）"
Write-Host "  [B] 仅停止后端容器 ai_assistant_app_prod"
Write-Host "  [C] 重启后端容器"
Write-Host "  [Q] 退出"
Write-Host ""

$choice = Read-Host "请选择 (A/B/C/Q)"

switch ($choice.ToUpper()) {
    "A" {
        Write-Host "停止生产容器（保留开发数据库）..." -ForegroundColor Yellow
        docker stop ai_assistant_app_prod ai_assistant_grafana ai_assistant_prometheus ai_memory_optimizer
        Write-Host "✓ 完成！现在可以运行 uvicorn main:app --reload" -ForegroundColor Green
    }
    "B" {
        Write-Host "停止后端容器..." -ForegroundColor Yellow
        docker stop ai_assistant_app_prod
        Write-Host "✓ 完成！现在可以运行 uvicorn main:app --reload" -ForegroundColor Green
    }
    "C" {
        Write-Host "重启后端容器..." -ForegroundColor Yellow
        docker restart ai_assistant_app_prod
        Write-Host "✓ 完成！等待 30 秒后运行 python frontend/app_enhanced.py" -ForegroundColor Green
    }
    "Q" {
        Write-Host "退出" -ForegroundColor White
    }
    default {
        Write-Host "无效选择" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "提示: 检查端口可用性: netstat -ano | findstr :8000" -ForegroundColor Cyan
