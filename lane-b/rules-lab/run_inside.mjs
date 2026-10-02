// Runs inside `firebase emulators:exec`: the B0 probe, then the studio rules suite. Writes probe.out / suite.out.
import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";
const run = (cmd) => { try { return execSync(cmd, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }); } catch (e) { return (e.stdout || "") + (e.stderr || ""); } };
writeFileSync("probe.out", run("node probe_b0.mjs firestore.rules"));
writeFileSync("suite.out", run("npx jest --config jest.config.js --runInBand 2>&1"));
