@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Telegram Math Bot - Grade 12 Yemen

rem ضع توكن البوت هنا (من @BotFather)
set TELEGRAM_BOT_TOKEN=PUT_YOUR_TOKEN_HERE

rem ضروري في اليمن حيث تلجرام محجوب — عدّل المنفذ حسب إعدادات Clash لديك
set TELEGRAM_PROXY=socks5://127.0.0.1:7897

rem معرفات المشرفين (افصل بينها بفاصلة) — أو أضفهم لاحقًا بأمر /addadmin
set BOT_ADMIN_IDS=

"C:\Users\ComputerWorld\AppData\Roaming\kimi-desktop\daimon-share\daimon\runtime\python\.venv\Scripts\python.exe" math_bot.py
pause
