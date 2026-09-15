# Architecture Overview

## Component Diagram

```mermaid
graph TD
    Client[Web Browser Client] -->|HTTPS/WSS| FastAPI[FastAPI Backend]
    
    subgraph Frontend
        Client
    end
    
    subgraph Backend Services
        FastAPI --> OCI_Auth[OCI Auth / Session]
        FastAPI --> OCI_GenAI[OCI Generative AI]
        FastAPI --> OCI_Speech[OCI Speech Services]
        FastAPI --> Fusion[Oracle Fusion Catalogue]
    end
    
    subgraph Observability
        Client --> Sentry[Sentry]
        FastAPI --> Sentry
    end
```

## Directory Structure
- `/frontend`: Contains the Vite + React application. State management via React Context. Tests located in `/frontend/tests`.
- `/backend`: Contains the FastAPI application. Core domain logic in `/backend/services`. Tests located in `/backend/tests`.
- `/deploy`: Contains infrastructure-as-code (Ansible playbooks) and Docker Compose definitions for environment parity.
- `/.github`: Contains GitHub Actions workflows for CI/CD, dependency management (Dependabot), and repository templates.
