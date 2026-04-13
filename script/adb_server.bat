```bat
@echo off
chcp 65001 >nul
title ADB 远程服务监控 (-a nodaemon)
color 0b

:loop
cls
echo ==============================================
echo    ADB 远程监听模式监控中 (所有网口)
echo    启动时间: %date% %time%
echo    模式: adb -a nodaemon server start
echo ==============================================
echo.

:: 1. 尝试启动 adb 服务
:: 使用 -a nodaemon 会阻塞窗口，直到进程崩溃或被关闭
adb -a nodaemon server start

:: 2. 如果 adb 退出，脚本会执行到这里
echo.
echo ----------------------------------------------
echo [警告] 检测到 ADB Server 已停止运行！
echo 正在清理残留进程并尝试重新启动...
echo ----------------------------------------------

:: 强制结束可能卡死的 adb 进程，确保端口 5037 释放
taskkill /f /im adb.exe >nul 2>&1

:: 等待 1 秒后重新进入循环
timeout /t 1 >nul
goto loop