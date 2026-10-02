#!/usr/bin/env bash
# Run the B0 probe and the studio rules suite against a rules file in the local emulator (synthetic data only).
#   bash run_lab.sh <rules-file> <label>
# Writes investigation/lane-b/rules-lab/results/<label>-probe.jsonl and <label>-studio-suite.txt
set -u
RULES="$1"; LABEL="$2"; SUITE="${3:-tests}"
LAB="C:/Users/kumar/AppData/Local/Temp/claude/e--OLBrain-Architecture-Research/06eb8791-1698-4139-a512-a56f3778dce3/scratchpad/rules-lab"
HERE="e:/OLBrain-Architecture-Research/investigation/lane-b/rules-lab"
mkdir -p "$HERE/results"
cp "$HERE/$RULES" "$LAB/firestore.rules"
rm -rf "$LAB/tests/firestore-rules"; mkdir -p "$LAB/tests/firestore-rules"; cp "$HERE/$SUITE/"* "$LAB/tests/firestore-rules/"
cp "$HERE/probe_b0.mjs" "$HERE/run_inside.mjs" "$LAB/"
cd "$LAB"
# stop any lingering LOCAL Firestore emulator (matched by its jar name only), which holds port 8080 on Windows
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='java.exe'\" | Where-Object { \$_.CommandLine -like '*cloud-firestore-emulator*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1
sleep 2
firebase emulators:exec --only firestore --project demo-olbrain-lab \
  "node run_inside.mjs" > emu.out 2>&1
grep "^{" probe.out > "$HERE/results/$LABEL-probe.jsonl"
cp suite.out "$HERE/results/$LABEL-studio-suite.txt"
grep -E "Tests:|Test Suites:" suite.out
python -c "
import json;r=[json.loads(l) for l in open(r'$HERE/results/$LABEL-probe.jsonl')]
print('probes',len(r),'attacks allowed',sum(x['attacker_allowed'] for x in r),'legit denied',sum(1 for x in r if x['legitimate_allowed'] is False))
for x in r:
  if x['attacker_allowed'] or x['legitimate_allowed'] is False: print('  ',x['id'],'attack',x['attacker_allowed'],'legit',x['legitimate_allowed'])"
