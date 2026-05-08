@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo [1/3] 複製資料檔...
copy /Y "dist\clears.json"       "docs\data\clears.json"      || goto :err
copy /Y "dist\player_bests.json" "docs\data\player_bests.json" || goto :err

echo [2/3] 更新 meta.json...
powershell -NoProfile -Command "$p=[IO.Path]::GetFullPath('docs\data\meta.json'); $t=Get-Date -Format 'yyyy-MM-dd HH:mm'; [IO.File]::WriteAllText($p,'{\"updated_at\":\"'+$t+'\"}')"

echo [3/3] 推送到 GitHub...
git add docs\data\
git diff --cached --quiet && echo 資料沒有變動，跳過 commit & goto :done
git commit -m "data: update %date% %time:~0,5%"
git push

:done
echo.
echo 完成！網站約 1 分鐘後更新。
pause
exit /b 0

:err
echo 錯誤：找不到 dist\ 資料檔，請先執行 TCtomestone.exe 抓資料。
pause
exit /b 1
