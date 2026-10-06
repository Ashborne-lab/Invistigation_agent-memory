#!/usr/bin/env bash
# Run a pytest command inside a LOCAL Firestore emulator (demo project, no credentials, synthetic data only).
#   bash run_emulator.sh <output-file> <pytest args...>
set -u
OUT="$1"; shift
CFG="C:/Users/kumar/AppData/Local/Temp/claude/e--OLBrain-Architecture-Research/06eb8791-1698-4139-a512-a56f3778dce3/scratchpad/storage-eval"
mkdir -p "$CFG"
printf '{"emulators":{"firestore":{"port":8086},"ui":{"enabled":false}}}' > "$CFG/firebase.json"
# stop a lingering LOCAL emulator only (matched by its jar name)
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='java.exe'\" | Where-Object { \$_.CommandLine -like '*cloud-firestore-emulator*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1
sleep 2
cd "$CFG"
firebase emulators:exec --only firestore --project demo-olbrain-storage-eval \
  "cd /d e:\\OLBrain-Architecture-Research\\investigation\\memory-prototype && python -m pytest $*" > "$OUT" 2>&1
grep -E "passed|failed|error|reached the emulator" "$OUT" | tail -5
