# Firestore rules unit tests

Executable checks on `firestore.rules` against the Firebase emulator — the
suites that pin who can read and write each collection.

These are the auditor evidence for the rules file, so they need to actually
run. Until recently they could not: `@firebase/rules-unit-testing` was present
in `node_modules` but declared in neither `package.json` nor the lockfile, so a
clean `npm ci` could not resolve it, and the jest this repo inherits from
`react-scripts` is 27, whose node environment predates global `fetch`. Every
suite died before its first assertion. Both are fixed; what follows is what is
left.

## Run

```
npm run test:rules
```

That starts the Firestore emulator and runs the suites against it. Nothing else
is needed — the dependency is declared, and `tests/firestore-rules/jest.config.js`
uses a small custom environment (`jest.environment.js`) that hands Node's
`fetch` family through to jest 27's sandbox.

## Java

`firebase-tools` needs **JDK 21 or newer** to start the emulator. A machine on
Java 17 fails with a version error before any test runs, which reads like a
broken suite and is not one:

```
export JAVA_HOME=$(/usr/libexec/java_home -v 23)
npm run test:rules
```

`brew install openjdk@23` if you do not have it.

## Writing a new suite

Name it `*.rules.test.js` in this directory and `testMatch` picks it up.

When you add a collection to an exclusion list in `firestore.rules`, add a case
here too. The suites are the only thing standing between a rules edit and a
production access change, and a rule nobody tests is a rule nobody notices
regressing — `research_plans` and `research_chat_sessions` were both added to
the write exclusions after a live hole was found by reading, not by a test.

## CI

Not wired yet. `npm run test:rules` is runnable locally and in any environment
with the JDK above; nothing gates a merge on it. Worth doing — the whole point
of this directory is to catch a rules regression before it ships, and today it
only catches one if somebody remembers to look.
