#!/usr/bin/env bash
# INV-S13 revocation probe against a rules file in the local emulator: bash run_revocation.sh <rules> <label>
set -u
LAB="C:/Users/kumar/AppData/Local/Temp/claude/e--OLBrain-Architecture-Research/06eb8791-1698-4139-a512-a56f3778dce3/scratchpad/rules-lab"
HERE="e:/OLBrain-Architecture-Research/investigation/lane-b/rules-lab"
cp "$HERE/$1" "$LAB/firestore.rules"; cp "$HERE/probe_revocation.mjs" "$LAB/"
cd "$LAB"
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='java.exe'\" | Where-Object { \$_.CommandLine -like '*cloud-firestore-emulator*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1
sleep 2
firebase emulators:exec --only firestore --project demo-olbrain-revoke "node probe_revocation.mjs firestore.rules" > rev.out 2>&1
grep "^{" rev.out > "$HERE/results/$2-revocation.jsonl"
python -c "
import json;r=[json.loads(l) for l in open(r'$HERE/results/$2-revocation.jsonl')]
print(len(r),'resources; INV-S13 holds for',sum(x['inv_s13_holds'] for x in r))
for x in r: print('  ',x['resource'].ljust(46),'before',x['allowed_before_revocation'],'after',x['allowed_after_revocation'])"
