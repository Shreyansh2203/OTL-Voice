# Configuration & Secrets Guide

This document provides a comprehensive guide for configuring all environment variables, OCI API keys, Oracle Cloud policies, and Oracle Fusion credentials.

---

## 1. Oracle Cloud Infrastructure (OCI) Setup

The backend communicates with OCI Generative AI and OCI AI Speech via the official Python OCI SDK.

### 1.1 Generating API Signing Keys

1. In the **OCI Console**, navigate to **Identity & Security** ➔ **Users** ➔ Select your User.
2. Under **Resources**, click **API Keys** ➔ **Add API Key**.
3. Choose **Generate API Key Pair**, download the Private Key (`.pem`), and click **Add**.
4. Copy the generated configuration snippet (User OCID, Tenancy OCID, Fingerprint, Region).

### 1.2 Supplying the Private Key

You can provide the private key in one of two ways:

#### Option A: Via File Path (Recommended)
Place the `.pem` file in your project or volume and set:
```bash
OCI_PRIVATE_KEY_PATH=/path/to/your_api_key.pem
```

#### Option B: Inline Environment Variable
Supply the full PEM string with line breaks encoded as `\n`:
```bash
OCI_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
```

### 1.3 Required OCI IAM Policies

Ensure the OCI User or Dynamic Group belongs to a group with policies granting inference and speech permissions:

```text
-- Allow GenAI model inference
ALLOW GROUP Developers TO USE generative-ai-family IN COMPARTMENT id ocid1.compartment.oc1..xxxx

-- Allow Speech synthesis (TTS)
ALLOW GROUP Developers TO USE ai-service-speech-family IN COMPARTMENT id ocid1.compartment.oc1..xxxx
```

---

## 2. Oracle Fusion Cloud HCM (OTL) Integration

The application writes timecard records to Oracle Fusion Cloud HCM via the standard REST resource:
`/hcmRestApi/resources/11.13.18.05/timeRecordEventRequests`

### 2.1 Service Account Requirements

The service account (`OTL_SERVICE_USERNAME` / `OTL_SERVICE_PASSWORD`) must have the following privileges in Oracle Fusion:
- **`HRC_REST_SERVICE_ACCESS_TIME_RECORD_EVENT_REQUESTS_RO_PRIV`** (Read)
- **`HRC_REST_SERVICE_ACCESS_TIME_RECORD_EVENT_REQUESTS_PRIV`** (Manage / Write)
- Assigned role: **Time and Labor Manager** or custom integration role.

### 2.2 Endpoint Configuration

Set the `OTL_BASE_URL` to your Oracle Fusion environment URL:

```bash
OTL_BASE_URL=https://<your-fusion-pod>.fa.ocs.oraclecloud.com/hcmRestApi/resources/11.13.18.05/timeRecordEventRequests
```

---

## 3. Environment Variable Reference

| Variable | Type | Default | Description |
| :--- | :---: | :---: | :--- |
| **`OCI_COMPARTMENT_ID`** | String | *None* | OCID of the target compartment where AI models are executed. |
| **`OCI_TENANCY_OCID`** | String | *None* | OCID of the root OCI tenancy. |
| **`OCI_USER_OCID`** | String | *None* | OCID of the OCI IAM user. |
| **`OCI_FINGERPRINT`** | String | *None* | Fingerprint of the uploaded RSA public key. |
| **`OCI_REGION`** | String | `us-ashburn-1` | OCI Region (e.g., `us-ashburn-1`, `us-phoenix-1`, `eu-frankfurt-1`). |
| **`OCI_PRIVATE_KEY_PATH`**| String | *None* | Filesystem path to the OCI RSA PEM private key. |
| **`CHAT_MODEL_ID`** | String | `google.gemini-2.5-flash` | GenAI model name or custom endpoint OCID. |
| **`CHAT_TEMPERATURE`** | Float | `0.3` | Model temperature (lower = more deterministic formatting). |
| **`CHAT_TOP_P`** | Float | `0.95` | Nucleus sampling probability threshold. |
| **`CHAT_MAX_TOKENS`** | Integer | `2048` | Maximum output generation tokens. |
| **`TTS_VOICE_ID`** | String | `Brian` | Neural voice identifier for OCI Speech TTS. |
| **`TTS_MODEL_NAME`** | String | `TTS_2_NATURAL` | TTS synthesis engine profile. |
| **`TTS_OUTPUT_FORMAT`** | String | `MP3` | Audio format (`MP3`, `OGG`, `PCM`). |
| **`OTL_BASE_URL`** | String | *Standard* | Fusion HCM REST API resource endpoint. |
| **`OTL_SERVICE_USERNAME`**| String | *None* | Integration service account username. |
| **`OTL_SERVICE_PASSWORD`**| String | *None* | Integration service account password. |
| **`STRICT_ASSIGNMENT`** | Boolean | `true` | When `true`, enforces strict project authorization. |
| **`SESSION_COOKIE_SECURE`**| Boolean| `false` | When `true`, sets `Secure` attribute on cookies (requires HTTPS). |
| **`SESSION_COOKIE_SAMESITE`**| String | `lax` | Cookie `SameSite` attribute (`lax`, `strict`, `none`). |
| **`SESSION_TTL_SECONDS`** | Integer | `28800` | Session lifetime in seconds (8 hours default). |
| **`OTL_DB_PATH`** | String | `./data/otl_dummy.db` | Local SQLite database file path. |
