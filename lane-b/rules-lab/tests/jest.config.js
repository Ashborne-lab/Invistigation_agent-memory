/**
 * Standalone jest config for the firestore rules suites.
 *
 * Deliberately separate from the CRA/craco test setup: these are node tests
 * against the Firestore emulator with no React, no jsdom, and no app modules,
 * and running them through react-scripts' config pulled in a browser
 * environment they have no use for.
 *
 * Run with: npm run test:rules  (starts the emulator, then this config)
 */
module.exports = {
  rootDir: __dirname,
  testEnvironment: require.resolve('./jest.environment.js'),
  testMatch: ['**/*.rules.test.js'],
  testTimeout: 30000,
};
