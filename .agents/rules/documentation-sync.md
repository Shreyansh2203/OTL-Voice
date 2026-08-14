---
name: documentation-sync
description: Enforce updating documentation across all relevant docs before committing and pushing code changes
trigger: always_on
---

# Documentation Sync Rule (Strict Requirement)

Whenever any modification is made to the codebase, you **MUST** ensure documentation is synchronized and up-to-date **before** committing and pushing changes to version control:

1. **API Endpoints & Contracts**: If any FastAPI route, request model, response schema, or error code changes in `backend/main.py` or services, update `docs/API.md` and `frontend/src/api/client.ts`.
2. **Environment Variables & Secrets**: If any new config or environment variable is added or changed, update `.env.example`, `docs/CONFIGURATION.md`, and the configuration table in `README.md`.
3. **Architecture & Flows**: If conversational logic, speech handling, or OTL submission flows change, update `docs/ARCHITECTURE.md`.
4. **Database & Reference Models**: If tables, columns, relations, views, or seed data change in `backend/db/`, update `docs/DATABASE.md` and `schema.sql`.
5. **Deployment & Operations**: If container build steps, Nginx configs, Docker Compose services, or volume mounts change, update `docs/DEPLOYMENT.md`, `Containerfile`, and `deploy/docker-compose.yml`.
6. **Verification Before Push**: Always verify that Python code compiles (`python -m py_compile ...`) and TypeScript types pass (`npm run typecheck`) before committing.
