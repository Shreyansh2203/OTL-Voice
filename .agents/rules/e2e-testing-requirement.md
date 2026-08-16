# E2E UI Testing Requirement

Whenever you make changes to the codebase (especially frontend UI components, API clients, or backend endpoints that affect the UI), you **MUST** test the UI end-to-end before considering the task complete.

1. **Run E2E Tests**: Navigate to the `frontend` directory and execute `npx playwright test` or `npm run test:e2e`.
2. **Verify Results**: Ensure all Playwright tests pass successfully.
3. **Fix Failures**: If any tests fail due to your changes (e.g. strict mode locator violations, missing elements, broken API mocks), you must fix the tests or fix your code so that the suite passes.
4. **No Unverified Commits**: Do not propose a final walkthrough or completion of a task without having a clean run of the E2E test suite.
