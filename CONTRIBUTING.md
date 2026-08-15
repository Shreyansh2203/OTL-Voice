# Contributing to OTL Voice Timesheet Assistant

Thank you for your interest in contributing to the **OTL Voice Timesheet Assistant**! This guide will help you set up your local development environment, understand our architecture, and submit high-quality contributions.

---

## Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free environment for everyone. Please be respectful, constructive, and collaborative in all interactions.

---

## Development Prerequisites

Ensure you have the following tools installed:

- **Python**: Version `3.12+` (or `3.14`)
- **Package Manager**: [`uv`](https://docs.astral.sh/uv/) (recommended for fast, deterministic Python management)
- **Node.js**: Version `20.x` or `22.x LTS`
- **Node Package Manager**: `npm` (bundled with Node)
- **Container Runtime (Optional)**: [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/)

---

## Local Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Shreyansh2203/OTL-Voice.git
cd OTL-Voice
```

### 2. Configure Environment Variables

Copy the example configuration and populate it with your development settings:

```bash
cp .env.example .env
```

Ensure your OCI PEM key file is accessible and properly referenced in `OCI_PRIVATE_KEY_PATH`.

### 3. Backend Setup

Initialize the virtual environment and synchronize dependencies using `uv`:

```bash
# Install dependencies into .venv
uv sync

# Run the FastAPI server in reload mode
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

The backend will load and cache catalogue data from Oracle Fusion APIs in a background thread on startup.

### 4. Frontend Setup

In a separate terminal window, start the Vite development server:

```bash
cd frontend
npm install
npm run dev
```

The frontend will start at `http://localhost:5173`. Vite's dev server is preconfigured to proxy `/api` requests directly to `http://localhost:8000`.

---

## Running with Docker Compose

To test the single-origin production container topology locally:

```bash
cd deploy
docker compose up --build
```

Access the application at `http://localhost`.

---

## Quality Standards & Validation

Before submitting your pull request, run the following verification steps:

### 1. Frontend Typecheck & Build

```bash
cd frontend
npm run typecheck
npm run build
```

### 2. Backend Code Compilation & Linting

```bash
# Verify Python syntax across all active backend modules
python -m py_compile backend/main.py backend/models.py backend/core/auth.py backend/services/chat.py backend/services/fusion_catalogue.py backend/services/oci_gemini.py backend/services/oci_speech.py backend/services/otl_client.py
```

### 3. Integration & Diagnostic Test Suites

Run the automated integration scripts to test Oracle Fusion connectivity, PPM catalogue lookups, and end-to-end validation flows:

```bash
# Test Oracle Fusion REST connectivity and worker query
python test_fusion_rest.py

# Test in-memory person index resolution and performance
python test_catalogue_lookup.py

# Run complete end-to-end simulation (Worker -> Assignments -> Prompt -> OTL submission)
python test_e2e_validation.py
```

---

## Coding Conventions

### Python (Backend)
- Follow **PEP 8** style guidelines.
- Use explicit type annotations for function signatures and return types (`typing`, `pydantic`).
- Maintain existing docstrings and comments for business logic.
- Isolate upstream I/O and external service calls inside `backend/services/`.

### TypeScript / React (Frontend)
- Use functional components with React hooks.
- Keep components focused, accessible, and responsive.
- Do not add heavy utility CSS frameworks (Tailwind); follow the custom design tokens in `frontend/src/index.css`.
- Ensure all asynchronous API calls handle errors gracefully with user-facing alerts.

---

## Git Workflow & Pull Requests

1. **Branch Naming**:
   - `feat/feature-name` for new capabilities.
   - `fix/bug-description` for bug fixes.
   - `docs/topic-name` for documentation updates.
   - `refactor/scope` for refactoring.

2. **Commit Messages**:
   - Use descriptive, imperative commit messages (e.g., `feat(speech): support custom sample rates in OCI TTS client`).

3. **Submitting PRs**:
   - Open a pull request against the `main` branch.
   - Include a concise summary of changes, motivation, and verification steps.
   - Attach screenshots or recordings for any UI/UX modifications.

---

## Need Help?

If you encounter any issues or have architectural questions, please open an [Issue](https://github.com/Shreyansh2203/OTL-Voice/issues) or reach out via project discussions.
