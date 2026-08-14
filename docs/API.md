# REST & SSE API Reference

The **OTL Timesheet Assistant** provides a REST and Server-Sent Events (SSE) API under the `/api` route prefix.

---

## 1. Authentication & Security

All API endpoints (except `/api/health`, `/api/health/otl`, and `/api/auth/login`) require an authenticated session.

- **Session Mechanism**: HttpOnly cookie named `otl_session`.
- **CSRF / SameSite**: `SameSite=Lax` (configurable).
- **Transport Security**: `Secure` cookie flag enabled in HTTPS environments via `SESSION_COOKIE_SECURE=true`.

---

## 2. Health Probes

### `GET /api/health`
Basic service liveness check.

#### Response
```json
{
  "status": "ok"
}
```

---

### `GET /api/health/otl`
Validates connectivity and credentials against upstream Oracle Fusion HCM REST API.

#### Response (Success)
```json
{
  "status": "ok",
  "endpoint": "https://fa-epxp-test-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/11.13.18.05/timeRecordEventRequests"
}
```

---

## 3. Authentication Endpoints

### `POST /api/auth/login`
Authenticates an employee and sets the `otl_session` HttpOnly cookie.

#### Request Body
```json
{
  "username": "suraj.yadav",
  "password": "Password123"
}
```

#### Response (`200 OK`)
```json
{
  "username": "suraj.yadav",
  "employeeId": "90407",
  "fullName": "Suraj Yadav"
}
```

#### Error Responses
- `401 Unauthorized`: Invalid credentials.

---

### `GET /api/auth/session`
Returns the current active employee identity.

#### Response (`200 OK`)
```json
{
  "username": "suraj.yadav",
  "employeeId": "90407",
  "fullName": "Suraj Yadav"
}
```

---

### `POST /api/auth/logout`
Terminates the active session and clears the cookie.

#### Response (`200 OK`)
```json
{
  "status": "signed out"
}
```

---

## 4. Conversational AI & Speech

### `POST /api/chat`
Streams assistant responses via Server-Sent Events (SSE) using OCI GenAI (Gemini 2.5 Flash).

#### Headers
- `Content-Type: application/json`
- `Accept: text/event-stream`

#### Request Body
```json
{
  "messages": [
    {
      "role": "user",
      "content": "I worked 8 hours on API design for Project 1001 today."
    }
  ]
}
```

#### Response Stream (`text/event-stream`)
```text
data: {"delta": "I've "}

data: {"delta": "noted 8 hours "}

data: {"delta": "for API design on Project 1001.\n\n```json\n{\n  \"entries\": [...]\n}\n```"}

data: [DONE]
```

---

### `POST /api/tts`
Synthesizes speech audio from provided text using OCI AI Speech Service.

#### Request Body
```json
{
  "text": "I've noted 8 hours for API design on Project 1001.",
  "rate": 1.0
}
```

#### Response (`200 OK`)
- **Content-Type**: `audio/mp3` (or configured MIME type).
- **Body**: Binary audio stream.

---

## 5. Labour Catalogue & Assignments

### `GET /api/labour/assignments`
Retrieves all work orders, project numbers, names, and allowable tasks assigned to the authenticated employee.

#### Response (`200 OK`)
```json
{
  "employeeId": "90407",
  "fullName": "Suraj Yadav",
  "workOrders": [
    {
      "workOrder": "WO-101",
      "description": "Core Cloud Platform Implementation",
      "projects": [
        {
          "projectNo": 1001,
          "projectName": "Project Alpha",
          "tasks": [
            "API Architecture & Integration",
            "Database Schema Design",
            "Performance Optimization"
          ]
        }
      ]
    }
  ]
}
```

---

## 6. Timesheet Operations

### `POST /api/otl/timecard`
Submits validated timecard entries to Oracle Fusion Cloud HCM.

#### Request Body (Option A: Explicit Entries)
```json
{
  "entries": [
    {
      "projectNo": 1001,
      "projectName": "Project Alpha",
      "workOrder": "WO-101",
      "taskDetails": "API Architecture & Integration",
      "hours": 8,
      "date": "2026-08-14"
    }
  ]
}
```

#### Request Body (Option B: Extraction from Assistant Message)
```json
{
  "assistantMessage": "Here is your summary: ```json\n{\"entries\": [{\"projectNo\": 1001, \"hours\": 8, \"date\": \"2026-08-14\", \"taskDetails\": \"API Architecture\"}]}\n```"
}
```

#### Response (`200 OK`)
```json
{
  "submitted": 1,
  "succeeded": 1,
  "failed": 0,
  "results": [
    {
      "ok": true,
      "entry": {
        "projectNo": 1001,
        "projectName": "Project Alpha",
        "workOrder": "WO-101",
        "taskDetails": "API Architecture & Integration",
        "hours": 8,
        "date": "2026-08-14",
        "employeeNumber": "90407",
        "employeeName": "Suraj Yadav"
      },
      "otlResponse": {
        "TimeRecordEventId": "300000012345678",
        "Status": "SUCCESS"
      }
    }
  ]
}
```

#### Error Response (`400 Bad Request`)
```json
{
  "detail": "Suraj Yadav is not assigned to project 2002 (Project Gamma). Assigned projects: 1001 (Project Alpha, WO WO-101)."
}
```

---

### `GET /api/otl/timecards`
Queries historical timecard entries submitted for the current employee from Oracle Fusion.

#### Query Parameters
- `limit` (integer, default `25`): Maximum records to fetch.
- `offset` (integer, default `0`): Pagination offset.

#### Response (`200 OK`)
```json
{
  "items": [
    {
      "TimeRecordEventId": "300000012345678",
      "Employee_Number_c": "90407",
      "Project_No_c": 1001,
      "Project_Name_c": "Project Alpha",
      "Work_Order_c": "WO-101",
      "Tasks_Details_c": "API Architecture & Integration",
      "Hours_c": 8,
      "Start_Time_c": "2026-08-14T09:00:00.000Z",
      "Stop_Time_c": "2026-08-14T17:00:00.000Z"
    }
  ],
  "hasMore": false,
  "limit": 25,
  "offset": 0
}
```

---

## 6. Labour Catalogue & Admin Endpoints

### `GET /api/labour/assignments`
Returns the assigned work orders, projects, and tasks for the currently authenticated employee.

#### Response (`200 OK`)
```json
{
  "employeeId": "90407",
  "fullName": "Suraj Yadav",
  "workOrders": [
    {
      "workOrder": "WO-101",
      "description": "Substation Preventive Maintenance",
      "projects": [
        {
          "projectNo": 1001,
          "projectName": "Project Alpha",
          "tasks": ["Transformer inspection", "Oil testing"]
        }
      ]
    }
  ]
}
```

---

### `POST /api/admin/refresh-catalogue`
Triggers an immediate background refresh of the Oracle Fusion HCM person-centric labour catalogue cache.

#### Response (`200 OK`)
```json
{
  "status": "refresh initiated"
}
```

---

### `GET /api/admin/catalogue-status`
Returns the current cache status and last synchronization timestamp of the labour catalogue.

#### Response (`200 OK`)
```json
{
  "status": "cached",
  "totalEmployees": 150,
  "lastSynced": "2026-08-14T20:00:00Z"
}
```
