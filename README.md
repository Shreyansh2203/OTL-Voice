# OTL Timesheet Assistant

The **OTL Timesheet Assistant** is an enterprise-grade web application designed to streamline time tracking and project management. It provides a robust voice-first conversational UI powered by Oracle Cloud Infrastructure (OCI) generative AI, backed by a FastAPI backend and a modern React frontend.

## 🏗️ Architecture

- **Frontend:** React, TypeScript, Vite, Tailwind CSS, Playwright (E2E testing), Vitest.
- **Backend:** Python (FastAPI), `uv` (dependency management), Pytest, OCI SDK.
- **Infrastructure:** Ansible (IaC), Docker, GitHub Container Registry (GHCR), DevContainers.
- **Observability:** Sentry for error tracking and performance monitoring.

## 🚀 Quick Start (Local Development)

The easiest way to get started is by using the provided DevContainer setup, or running it locally via Docker Compose.

### Prerequisites
- [Docker](https://www.docker.com/)
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [pnpm](https://pnpm.io/) (Frontend package manager)

### 1. Environment Setup

Copy the example environment file and fill in your OCI credentials:

```bash
cp .env.example .env
```

### 2. Running Locally (Docker)

To spin up the entire stack using Docker Compose:

```bash
./start.sh
```

### 3. Running Locally (Native)

To run the application natively with hot-reloading for both the frontend and backend:

```bash
./dev.sh
```

## 🧪 Testing

The repository maintains strict unit and end-to-end testing standards.

**Run Backend Tests:**
```bash
uv run pytest backend/tests
```

**Run Frontend Tests:**
```bash
cd frontend && pnpm test
```

**Run E2E Playwright Tests:**
```bash
cd frontend && pnpm run test:e2e
```

## 🚢 CI/CD & Releases

This project utilizes GitHub Actions for continuous integration and deployment:
- **CI Pipeline:** Automatically runs linters, unit tests, E2E tests, and CodeQL security scans on every PR and push to `main`.
- **CD Pipeline:** Automatically builds and pushes the production Docker image to the GitHub Container Registry (`ghcr.io`) upon a new release.
- **Release Please:** Automates semantic versioning and changelog generation based on Conventional Commits.

## 🛡️ Contributing

Please review the `.github/CODEOWNERS` and ensure all PRs conform to the provided Pull Request template. All commits must follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.
