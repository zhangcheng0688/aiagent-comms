#!/bin/zsh
URL="http://127.0.0.1:8766/static/business-plan.html"
D="/Applications/MiniMax Code.app/Contents/Resources/resources/daemon/cli.js"

navigate() { node "$D" mcp call playwright browser_navigate "{\"url\":\"$URL\"}" 2>&1 | tail -1; }
evaluate() { node "$D" mcp call playwright browser_evaluate "{\"function\":\"() => { window.scrollTo(0, $1); return $1; }\"}" 2>&1 | tail -1; }
screenshot() { node "$D" mcp call playwright browser_take_screenshot "{\"type\":\"jpeg\",\"filename\":\"$1.jpg\",\"fullPage\":false}" 2>&1 | tail -1; }

navigate
sleep 6
for n in 1 3 6 9 12 15; do
  py=$(( (n - 1) * 929 ))
  evaluate $py
  sleep 3
  screenshot "bpy$n"
done
ls -t /Users/chenwanyi/.mavis/tmp/mcp-images/ | head -8
