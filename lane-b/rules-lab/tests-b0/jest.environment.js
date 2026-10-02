/**
 * Node test environment with the global fetch family restored.
 *
 * Why this file exists: @firebase/rules-unit-testing talks to the emulator over
 * fetch, and the jest this repo gets transitively from react-scripts is 27,
 * whose node environment predates global fetch and does not forward it from the
 * host. So every rules suite died with "fetch is not defined" before reaching a
 * single assertion — the finance and clix suites included, which is why the
 * comment in firestore.finance.rules.test.js calling the suite "the auditor
 * evidence" had quietly stopped being true.
 *
 * The alternative was adding jest 29 as a second copy alongside react-scripts'.
 * This is cheaper and touches nothing the app build uses: the parent process is
 * Node 18+, so these globals exist here and are simply handed through.
 */
/* eslint-env node */
/* globals globalThis, structuredClone */
const NodeEnvironment = require('jest-environment-node').default
  || require('jest-environment-node');

class RulesTestEnvironment extends NodeEnvironment {
  async setup() {
    await super.setup();
    for (const name of ['fetch', 'Headers', 'Request', 'Response', 'FormData', 'Blob']) {
      if (this.global[name] === undefined && typeof globalThis[name] !== 'undefined') {
        this.global[name] = globalThis[name];
      }
    }
    // structuredClone is used by the firebase SDK's internals on some paths and
    // is likewise absent from jest 27's sandbox.
    if (this.global.structuredClone === undefined && typeof structuredClone !== 'undefined') {
      this.global.structuredClone = structuredClone;
    }
  }
}

module.exports = RulesTestEnvironment;
