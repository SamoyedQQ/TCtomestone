@echo off
echo Fetching latest from remote...
git fetch origin

echo Restoring data files from remote (clears, player_bests, meta, processed_codes)...
git checkout origin/master -- docs/data/clears.json docs/data/player_bests.json docs/data/meta.json docs/data/processed_codes.json

echo Pulling code changes (HTML/CSS/JS)...
git pull --rebase --autostash origin master

echo Done.
pause
