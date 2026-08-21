<div align="center">

# 🎙️ OTL Voice Timesheet Assistant

**An intelligent, voice-powered enterprise timesheet assistant for Oracle Time and Labor (OTL), powered by OCI GenAI (Gemini 2.5 Flash), OCI Speech Synthesis, and FastAPI.**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-Swagger%20UI-85EA2D.svg?logo=swagger&logoColor=black)](http://localhost:8000/docs)
[![React](https://img.shields.io/badge/React-18.3-61DAFB.svg?logo=react&logoColor=black)](https://reactjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![OCI GenAI](https://img.shields.io/badge/OCI-Generative%20AI%20(Gemini%202.5)-F80000.svg?logo=oracle&logoColor=white)](https://www.oracle.com/artificial-intelligence/generative-ai/generative-ai-service/)
[![Docker](https://img.shields.io/badge/Docker-Single--Origin-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Features](#-key-features) • [Architecture](#-architecture) • [Quickstart](#-quickstart) • [Documentation](#-documentation-index) • [Configuration](#-configuration) • [Contributing](CONTRIBUTING.md)

</div>

---

## 📖 Overview

Logging timesheets in enterprise ERP systems like **Oracle Fusion Cloud HCM (Time and Labor / OTL)** can be tedious, multi-step, and error-prone. 

The **OTL Voice Timesheet Assistant** transforms this experience into a frictionless, natural conversation. Employees simply speak or type their daily accomplishments (e.g., *"I worked 5 hours on API integration for Project Alpha and 3 hours on client debugging"*). The assistant:

1. **Transcribes voice input in real-time** via the browser Web Speech API.
2. **Understands contextual project assignments** via **Google Gemini 2.5 Flash** hosted on **Oracle Cloud Infrastructure (OCI) Generative AI**.
3. **Validates work orders, projects, and task details** against local reference data with strict authorization checks.
4. **Submits structured timecards directly** to Oracle Fusion's REST API (`timeRecordEventRequests`).
5. **Responds with natural speech synthesis** powered by **OCI AI Speech Service (TTS)**.

---

## ✨ Key Features

- **🗣️ Natural Voice & Text Conversational Interface**: Speak or type naturally; the assistant extracts project numbers, hours, dates, and task descriptions automatically.
- **⚡ Real-Time Streaming SSE**: Streaming chat tokens delivered instantly to the UI via Server-Sent Events (SSE).
- **🔊 OCI Speech Synthesis (TTS)**: Clean, punctuation-stripped natural voice readout of assistant responses using OCI AI Speech.
- **🔒 Context-Aware Security & Assignment Guard**: Automatically injects signed-in employee identity and assigned work orders into the prompt context. Prevents unauthorized time logging against unassigned projects.
- **📱 Installable Progressive Web App (PWA)**: Built with React, TypeScript, and Vite with offline manifest, service worker, and mobile-responsive viewport.
- **📦 Single-Origin Production Container**: Multi-stage build packing the React PWA and FastAPI backend into a single container fronted by Nginx with TLS readiness.
- **📊 Excel Export & Audit Trail**: Comprehensive utilities for exporting timesheet records and employee assignments to spreadsheet formats.

---

## 🏛️ Architecture

```mermaid
flowchart TB
    subgraph Client["Client Tier (Browser / PWA)"]
        UI["React 18 + TypeScript PWA"]
        Mic["Microphone (Web Speech API)"]
        Audio["Audio Player (OCI TTS)"]
    end

    subgraph Gateway["Reverse Proxy & Gateway"]
        Nginx["Nginx (Port 80 / 443 TLS)"]
    end

    subgraph Backend["Application Tier (FastAPI)"]
        API["FastAPI Backend (:8000)"]
        Auth["Auth & Session Manager"]
        ChatEngine["Chat & Prompt Engine"]
        OTLService["OTL REST Client"]
    end

    subgraph Cloud["External Services (OCI & Oracle Cloud)"]
        OCIGenAI["OCI GenAI Service\n(Gemini 2.5 Flash)"]
        OCISpeech["OCI AI Speech Service\n(Neural TTS)"]
        FusionOTL["Oracle Fusion HCM\n(timeRecordEventRequests)"]
    end

    UI <-->|HTTP / SSE / Static| Nginx
    Mic --> UI
    UI --> Audio
    Nginx <-->|Reverse Proxy| API

    API --> Auth
    API --> ChatEngine
    API --> OTLService
    
    ChatEngine <-->|Generative AI Inference| OCIGenAI
    API <-->|Speech Synthesis| OCISpeech
    OTLService <-->|REST API JSON| FusionOTL
```

---

## 🚀 Quickstart

### Option 1: Quick Launch (Pre-Flight Checks + Automated Start)

Launch the full stack with automatic pre-flight verification (validates Docker daemon status and `.env` configuration) and browser launch:

- **Windows**: Double-click `start.bat` or run:
  ```bat
  start.bat
  ```
  *(Validates Docker Desktop is running and `.env` exists before starting)*

- **Linux / macOS**: Run `./start.sh` or use `make`:
  ```bash
  chmod +x start.sh && ./start.sh
  # or
  make
  ```
  *(Cross-platform Makefile supporting `make up`, `make down`, `make build`, `make shell`, `make logs`, `make status`)*

---

### Option 2: Docker Compose

1. Clone repository and copy `.env.example`:
   ```bash
   git clone https://github.com/Shreyansh2203/OTL-Voice.git
   cd OTL-Voice
   cp .env.example .env
   ```
2. Configure your OCI and Oracle credentials in `.env`.
3. Launch with Docker Compose:
   ```bash
   cd deploy
   docker compose up --build
   ```
4. Access the web interface at `http://localhost`.

---

### Option 3: Local Development (Hot Reloading)

#### Prerequisites
- Python 3.12+ with [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ with `npm`

#### Quick Start (Both Servers)

Run the included development script to start both the FastAPI backend and the React frontend in a single terminal with color-coded logs:

- **Windows**: Double-click `dev.bat` or run:
  ```bat
  dev.bat
  ```

- **Linux / macOS**: Run `./dev.sh`:
  ```bash
  chmod +x dev.sh && ./dev.sh
  ```

Visit `http://localhost:5173`. Vite automatically proxies `/api` requests to the FastAPI backend at port 8000.

---

## 📂 Project Structure

```text
timesheet-repo/
├── backend/
│   ├── core/
│   │   └── auth.py              # Identity tracking & session cookie management
│   ├── models.py                # Core domain models (Employee)
│   ├── prompts/
│   │   └── prompt.txt           # Context-engineered system prompt for Gemini
│   ├── services/
│   │   ├── chat.py              # SSE chat stream generator & prompt builder
│   │   ├── fusion_catalogue.py  # Live in-memory PPM/HCM catalogue & auto-refresher
│   │   ├── oci_gemini.py        # OCI GenAI client (Gemini 2.5 Flash)
│   │   ├── oci_speech.py        # OCI Speech TTS client & markdown sanitizer
│   │   └── otl_client.py        # Oracle Fusion OTL REST client
│   └── main.py                  # FastAPI application & route definitions
├── data/                        # Person-centric master catalogues & exported worker files
│   ├── fusion_person_master.json # Mapped employee-to-project catalogue
│   ├── fusion_person_master.xlsx # Consolidated multi-sheet Excel workbook
│   └── fusion_employees.csv     # Extracted worker roster from Oracle Fusion
├── frontend/
│   ├── src/
│   │   ├── api/client.ts        # Typed API & SSE streaming client
│   │   ├── components/          # ChatView, Composer, ReviewPanel, LoginView
│   │   ├── lib/                 # Audio player & SSE parser
│   │   ├── App.tsx              # Main application shell
│   │   └── index.css            # Custom responsive CSS design system
│   ├── package.json             # Frontend dependencies & scripts
│   └── vite.config.ts           # Vite + PWA configuration
├── deploy/
│   ├── docker-compose.yml       # Production container orchestration
│   └── nginx/otl.conf           # Nginx reverse proxy configuration
├── docs/                        # Deep-dive documentation
│   ├── ARCHITECTURE.md          # System architecture, prompt flow, and logic
│   ├── API.md                   # REST API & SSE streaming documentation
│   ├── CONFIGURATION.md         # Environment variables and IAM setups
│   ├── DATA_CATALOGUE.md        # Fusion PPM/HCM catalogue, pipelines & data architecture
│   └── DEPLOYMENT.md            # Docker, Nginx, batch launchers, and production hosting
├── scripts/
│   ├── build_person_centric_catalogue.py # JSON/XLSX person-centric transformer
│   ├── explore_fusion.py            # Interactive CLI explorer for Fusion REST endpoints
│   └── scratch/                     # One-off local dev/debug scripts (gitignored)
├── test_*.py                        # Root-level integration test scripts
├── .env.example                 # Sanitized environment template
├── Containerfile                # Multi-stage production container build
├── CONTRIBUTING.md              # Contributor onboarding, testing & guidelines
├── LICENSE                      # MIT License
├── Makefile                     # Standard lifecycle automation targets
├── pyproject.toml               # Python project configuration (uv)
├── start.bat                    # One-click Windows launcher with pre-flight checks
└── start.sh                     # One-click Linux/macOS launcher with pre-flight checks
```

---

## 📚 Documentation Index

For detailed technical references, refer to the guides in the [`docs/`](docs/) directory:

| Guide | Description |
| :--- | :--- |
| **[Architecture Guide](docs/ARCHITECTURE.md)** | End-to-end data flows, voice pipeline, SSE protocol, and security model. |
| **[API Reference](docs/API.md)** | REST endpoints, SSE streams, Person Number authentication, and admin refresh routes. |
| **[Interactive API Docs](http://localhost:8000/docs)** | Auto-generated OpenAPI / Swagger UI for testing endpoints locally. |
| **[Configuration Guide](docs/CONFIGURATION.md)** | Available environment variables, OCI IAM policies, and Oracle Fusion permissions. |
| **[Data Catalogue Guide](docs/DATA_CATALOGUE.md)** | Live Fusion PPM in-memory caching, data extraction scripts, and offline master files. |
| **[Deployment Guide](docs/DEPLOYMENT.md)** | Single-container deployments, Nginx TLS, Docker Compose, and batch commands. |

---

## ⚙️ Configuration

Key environment variables in `.env`:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `OCI_COMPARTMENT_ID` | OCI Compartment OCID hosting GenAI & Speech | *Required* |
| `OCI_USER_OCID` | OCI User OCID for API signing | *Required* |
| `OCI_TENANCY_OCID` | OCI Tenancy OCID | *Required* |
| `OCI_FINGERPRINT` | Fingerprint of uploaded OCI public key | *Required* |
| `OCI_REGION` | OCI Region identifier | `us-ashburn-1` |
| `OCI_PRIVATE_KEY_PATH` | Path to private RSA PEM key | `./oci_api_key.pem` |
| `CHAT_MODEL_ID` | GenAI model OCID / ID | `google.gemini-2.5-flash` |
| `OTL_BASE_URL` | Oracle Fusion Timecard API endpoint | *Fusion SaaS URL* |
| `OTL_SERVICE_USERNAME` | Service account username for Fusion HCM | *Required* |
| `OTL_SERVICE_PASSWORD` | Service account password for Fusion HCM | *Required* |
| `CATALOGUE_REFRESH_SECONDS` | In-memory Fusion PPM catalogue auto-refresh interval | `21600` (6h) |
| `STRICT_ASSIGNMENT` | Enforce employee project assignment checks | `true` |
| `DEFAULT_START_HOUR` | Default start hour for timecards when none is inferred | `9` |
| `DEFAULT_EXPENDITURE_TYPE` | Default expenditure type string for project-based entries | `Professional Services` |
| `SESSION_COOKIE_SECURE` | Set `Secure` flag on session cookie (set `true` with HTTPS) | `false` |

*(See [.env.example](.env.example) and [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for full details).*

---

## 🛠️ Technology Stack

- **Frontend UI**: React 18, TypeScript, Tailwind CSS, Vite.
- **Backend API**: Python 3.12+, FastAPI, Pydantic, Uvicorn.
- **AI Integration**: Google Gemini (`gemini-2.5-flash`), Oracle Cloud Infrastructure (OCI) SDK, OCI Generative AI Inference, OCI AI Speech Service.
- **DevOps**: Docker, Podman/Containerfile, Nginx, Docker Compose.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
