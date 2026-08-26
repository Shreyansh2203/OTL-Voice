# 🎙️ OTL Voice-Enabled AI Timesheet Assistant

An enterprise-grade, voice-first AI timesheet assistant for **Oracle Time and Labor (OTL)**. Built with **FastAPI**, **React 18 (PWA)**, **OCI GenAI (Gemini)**, and **OCI Speech (STT / TTS)**.

---

## 🌟 Highlights & Features

- **🗣️ Natural Conversational Timesheet Filing**: Speak or type work hours, project tasks, and comments naturally.
- **⚡ Real-Time Streaming & Speech Synthesis**: Low-latency Server-Sent Events (SSE) chat streaming and OCI Speech WebSocket streaming.
- **🏢 Fusion Labour Assignment Catalogue**: Real-time worker assignment indexing and validation against assigned projects and work orders.
- **🔒 Enterprise Security**:
  - Encrypted, HMAC-signed session cookies with configurable SameSite & Secure flags.
  - Anti-CSRF double-submit token verification on all state-changing endpoints.
  - Granular in-memory/Redis rate limiting and strict WebSocket origin enforcement.
  - Strict Content-Security-Policy (CSP) headers.
- **📱 Installable PWA**: React 18 + Vite Progressive Web App with offline caching and mobile-first responsive layout.
- **🧩 10/10 Clean Architecture**:
  - Backend: Modular FastAPI `APIRouter` structure (`backend/api/v1/`), typed Pydantic DTOs, and isolated domain services.
  - Frontend: Feature-Sliced Architecture (`src/features/`) with isolated UI atomics (`src/components/ui/`).

---

## 🏗️ Architecture Overview

```
                        +----------------------------+
                        |   React 18 + Vite (PWA)    |
                        | (Features: Chat/Auth/OTL)  |
                        +--------------+-------------+
                                       |
                   HTTP / SSE / WS     |   CSRF & Session Cookies
                                       v
                        +----------------------------+
                        |      FastAPI Backend       |
                        |   (backend/api/v1/router)  |
                        +--------------+-------------+
                                       |
         +-----------------------------+-----------------------------+
         |                             |                             |
         v                             v                             v
+------------------+         +--------------------+        +--------------------+
|  OCI GenAI LLM   |         |     OCI Speech     |        | Oracle Cloud OTL   |
| (Gemini Agentic) |         | (Realtime STT/TTS) |        | (Timecards & PPM)  |
+------------------+         +--------------------+        +--------------------+
```

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.12+** and [uv](https://docs.astral.sh/uv/) package manager.
- **Node.js 20+** and `npm`.
- *(Optional)* Docker & Docker Compose for containerized deployment.

### 1. Clone & Configure Environment
```bash
git clone https://github.com/Shreyansh2203/OTL-Voice.git
cd OTL-Voice
cp .env.example .env
# Edit .env with your OTL and OCI credentials
```

### 2. Run in Development Mode (Hot-Reload)

**Windows:**
```cmd
.\dev.bat
```

**macOS / Linux:**
```bash
chmod +x dev.sh && ./dev.sh
```

- Backend API: `http://localhost:8000` (Interactive API Docs: `http://localhost:8000/docs`)
- Frontend Dev Server: `http://localhost:5173`

---

## 🧪 Testing & Quality Assurance

The codebase features 100% passing tests, strict linting, and comprehensive static typing.

```bash
# Run all verification checks at once
make test-all

# Or run individual suites:
uv run pytest --cov=backend       # Backend unit & integration tests (110 tests)
uv run ruff check .                # Python linting
uv run mypy backend                # Python typechecking (31 source files)
npm --prefix frontend run test:unit # Frontend Vitest suites (105 tests across 15 suites)
npm --prefix frontend run lint      # Frontend ESLint
npm --prefix frontend run typecheck # Frontend TypeScript check
npm --prefix frontend run build     # Frontend production build
```

---

## 📂 Project Directory Structure

```
timesheet-repo/
├── backend/
│   ├── api/
│   │   └── v1/                      # Modular FastAPI API Routers
│   │       ├── auth.py              # Session, login/logout routes
│   │       ├── chat.py              # LLM streaming, TTS synthesis, STT WebSocket
│   │       ├── health.py            # System & OTL dependency health checks
│   │       ├── router.py            # Router aggregator mounting /api/v1
│   │       └── timecards.py         # Timecard creation, listing, labour assignments
│   ├── core/
│   │   ├── auth.py                  # HMAC session signing, CSRF validation, cookies
│   │   └── limiter.py               # Rate limiting & WebSocket connection tracking
│   ├── schemas/                     # Pydantic request/response models & protocols
│   ├── services/
│   │   ├── chat.py                  # Agentic prompt orchestration & tool routing
│   │   ├── fusion_catalogue.py      # Background worker assignment indexing & cache
│   │   ├── oci_gemini.py            # Gemini client & live tools
│   │   ├── oci_speech.py            # TTS/STT client interfaces
│   │   └── otl_client.py            # Oracle Time & Labor REST client
│   ├── tests/                       # 110 unit & integration pytest tests
│   └── main.py                      # Application entrypoint & static SPA mounting
│
├── frontend/
│   ├── src/
│   │   ├── api/                     # Type-safe API client & error handling
│   │   ├── components/
│   │   │   └── ui/                  # Shared UI primitives (ToolChip, ThinkingState, icons)
│   │   ├── features/
│   │   │   ├── auth/                # LoginView, credentials validation & tests
│   │   │   ├── chat/                # ChatView, Composer, MessageBubble & tests
│   │   │   └── timesheets/          # ReviewPanel, TimecardHistory, ProjectAssignments
│   │   ├── lib/                     # Audio synthesis, SSE parser, speech input
│   │   ├── App.tsx                  # Root state & session boundary
│   │   └── main.tsx                 # React DOM bootstrapping & PWA service worker
│   └── dist/                        # Production build output
│
├── scripts/
│   ├── diagnostics/                 # Isolated API & backend diagnostics utilities
│   ├── build_person_centric_catalogue.py
│   ├── explore_fusion.py
│   └── strip_python_comments.py
│
├── deploy/                          # Production Docker Compose & Nginx configs
├── Containerfile                    # Multi-stage container build
├── Makefile                         # Unified development & test CLI
├── pyproject.toml                   # Standardized Python build & test tooling
└── uv.lock                          # Deterministic Python lockfile
```

---

## 🐳 Containerized Production Deployment

Build and run the single-origin container behind an Nginx reverse proxy:

```bash
cd deploy
docker compose up --build -d
```

The container automatically serves the compiled React PWA and FastAPI endpoints from a single origin on port 80.

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
