## Mandatory Post-Change Engineering Checklist

After making ANY code change, the agent MUST complete and verify all of the following before considering the task complete:

1. Test the UI end-to-end.
2. Test the frontend end-to-end.
3. Test the backend end-to-end.
4. Verify frontend ↔ backend integration works correctly.
5. Run appropriate unit tests, integration tests, and other tests required by industry best practices.
6. Verify the CI/CD pipeline is working and all relevant checks pass.
7. Commit the completed changes.
8. Push the changes to GitHub.

Completion requirements:
- Do not declare the task complete until the applicable checks above have been performed.
- If a required test cannot be run, clearly state which test was not run and why.
- If a test fails, investigate and fix the issue before declaring the task complete.
- Do not skip testing merely because the code change appears small.
- After fixing a test failure, rerun the affected tests and relevant end-to-end tests.
- Verify that frontend and backend changes work together, not just independently.
- Before pushing, ensure the working tree contains only intended changes.
- After pushing, verify the push succeeded and, where possible, verify the CI/CD checks triggered by the push.
- Report the tests/checks performed and their results in the final response.

This checklist is mandatory for every code-change task unless the user explicitly instructs otherwise.
