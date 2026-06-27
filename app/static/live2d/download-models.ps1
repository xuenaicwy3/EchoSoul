# EchoSoul Live2D 模型下载脚本
# 免费样品模型来源: Live2D 官方网站
#
# Haru (免费): https://www.live2d.com/download/sample-data/
# Hiyori (免费): https://www.live2d.com/download/sample-data/
#
# 手动下载步骤:
# 1. 访问 https://www.live2d.com/en/download/sample-data/
# 2. 下载 Haru 和 Hiyori 的 Cubism 4 模型包
# 3. 解压到对应目录:
#    - Haru → frontend/public/live2d/haru/
#    - Hiyori → frontend/public/live2d/hiyori/
#
# 目录结构示例:
# public/live2d/haru/
#   haru_greeter_t01.model3.json
#   haru_greeter_t01.moc3
#   haru_greeter_t01.2048/texture_00.png
#   motions/
#   expressions/
#
# 验证: 启动后访问 http://127.0.0.1:8000/chat
# 右侧应显示 Live2D 角色

Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  EchoSoul Live2D 模型下载" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "请手动下载免费模型:" -ForegroundColor Yellow
Write-Host "1. https://www.live2d.com/en/download/sample-data/" -ForegroundColor Cyan
Write-Host "2. 搜索 'Haru' 和 'Hiyori' (Cubism 4 SDK)" -ForegroundColor Cyan
Write-Host "3. 下载并解压到对应目录" -ForegroundColor Cyan
Write-Host ""
Write-Host "Haru 模型 → frontend/public/live2d/haru/" -ForegroundColor Green
Write-Host "Hiyori 模型 → frontend/public/live2d/hiyori/" -ForegroundColor Green
Write-Host ""
Write-Host "当前模型目录状态:" -ForegroundColor Yellow

$haruJson = Get-ChildItem -Path "haru" -Filter "*.model3.json" -ErrorAction SilentlyContinue
$hiyoriJson = Get-ChildItem -Path "hiyori" -Filter "*.model3.json" -ErrorAction SilentlyContinue

if ($haruJson) { Write-Host "  [OK] Haru: $($haruJson.Name)" -ForegroundColor Green }
else { Write-Host "  [MISSING] Haru — 需要下载" -ForegroundColor Red }

if ($hiyoriJson) { Write-Host "  [OK] Hiyori: $($hiyoriJson.Name)" -ForegroundColor Green }
else { Write-Host "  [MISSING] Hiyori — 需要下载" -ForegroundColor Red }
