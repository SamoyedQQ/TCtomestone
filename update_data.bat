@echo off
echo Copying data files...
copy /Y "dist\clears.json"       "docs\data\clears.json"
copy /Y "dist\player_bests.json" "docs\data\player_bests.json"
echo Generating meta.json...
powershell -NoProfile -Command "$p=[IO.Path]::GetFullPath('docs\data\meta.json'); $t=Get-Date -Format 'yyyy-MM-dd HH:mm'; [IO.File]::WriteAllText($p,'{\"updated_at\":\"'+$t+'\"}')"
echo Done.
pause
