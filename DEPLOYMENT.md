# Deployment Policy

The only deployed application environment is the current Render service sourced from the `main` branch.

Deployment flow:

1. Develop on an isolated feature or hotfix branch.
2. Open a pull request targeting `main`.
3. Require the application test suite to pass.
4. Merge to `main`.
5. Render deploys the current `main` commit.

Do not deploy application branches directly to Render. Do not use staging Render Blueprints or staging deployment branches.
