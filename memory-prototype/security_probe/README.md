# Firestore rules probe (Lane A, A9: security)

Runs the CURRENT production `firestore.rules` (olbrain-studio@1f05ca11, read-only copy) in the local Firestore
emulator (project `demo-olbrain-probe`, so no real project is involved) and records what a signed-in user from
ANOTHER org can do. Synthetic data only. Nothing here changes rules or touches production.

Run (needs Node 22, Java 21+, firebase-tools):

    git -C ../../../repos/olbrain-studio show origin/main:firestore.rules > firestore.rules
    npm install && firebase emulators:exec --only firestore --project demo-olbrain-probe "node probe.mjs"

`results-studio-1f05ca11.jsonl` holds the 2026-10-01 result. `allowed_for_other_org_user: true` is an exposure.
Lane B re-runs this file against the fixed rules; every line in the security gate (G-SEC) must flip to false,
except the probes that are deliberately allowed after the fix (none in this set).

Caveat: this proves what the rules FILE permits. Whether this exact file is what is deployed is [UNRESOLVED]
(no deploy configuration in the workspace).
