# CPM Ground Installation & Evidence — Central Backend

FastAPI + SQLAlchemy implementation of the API layer from the PRD (sections 56–75, 88, 98, 99).
It is the **central visibility + audit + sync** half of the platform: the mobile Ground App
captures evidence at the source, this service preserves it and makes it available to
authorized stakeholders and (later) the CPM Portal.

- Evidence **binary** lives in object storage (local disk now, S3/MinIO in production).
- **PostgreSQL** (SQLite for local dev) holds metadata, hashes, references, and the append‑only audit log.
- Authorization is enforced **server‑side** — the mobile app is never the sole authz layer.

---

## Quick start (Windows / PowerShell)

```powershell
cd C:\Users\Administrator\Desktop\cpm-ground-app\backend
.\run.ps1
```

`run.ps1` creates a virtualenv, installs deps, runs the **end‑to‑end smoke test**, then starts the API.

| | |
|---|---|
| API root | http://127.0.0.1:8000/ |
| **Interactive docs (Swagger)** | http://127.0.0.1:8000/docs |
| OpenAPI JSON | http://127.0.0.1:8000/openapi.json |
| Health | http://127.0.0.1:8000/api/v1/health |

Manual equivalents:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe smoke_test.py          # prove the evidence chain, no server needed
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The database (`data/cpm.db`) and evidence (`data/objects/`) are created on first run and
**seeded** with the same demo projects, centers and users as the mobile test client.

### Demo accounts

| Login | Credentials | Role |
|---|---|---|
| OTP | mobile `9876543210` → code returned in the response (`CPM_EXPOSE_OTP=true`) | Technician (`TCH-008`) |
| Vendor code | `VEND-ARC-12` / `demo1234` | Technician (`TCH-008`) |
| Vendor code | `CPM-MENON` / `demo1234` | CPM (read‑only stakeholder) |
| Vendor code | `OPS-DESK` / `demo1234` | Operations |
| Vendor code | `ADMIN` / `admin1234` | System Administrator |

---

## What the smoke test proves

`python smoke_test.py` walks the full chain and prints `[PASS]/[FAIL]` per PRD acceptance
criterion (§101–107):

- OTP **and** vendor‑code auth; refresh‑token rotation; unauthenticated requests blocked
- Installation session with **idempotent create** (`client_uuid`)
- Selfie + CCTV/Monitor/UPS/Router evidence upload — GPS + technician bound to every record, SHA‑256 stored
- **Idempotency‑Key** replay returns the same evidence id — a retry never duplicates (§64)
- Duplicate **camera number** blocked; duplicate **serial** surfaced but not silently merged (§35)
- Compliance computed **independently** of technician status; missing cameras surfaced, not hidden (§19)
- Submission keeps the technician's status verbatim; returns completion‑warning data (§19, §20)
- Sync session → acknowledge returns the authoritative evidence id/hash list for client reconciliation (§50)
- Post‑submission **replace** keeps the prior version; **delete** is refused after submission (§40, §41)
- Timeline is chronological and complete (CREATED → SUBMITTED → SYNCED → REPLACED) (§91)
- **RBAC server‑side**: CPM can view submitted installations but cannot create or delete (§72)
- Evidence served only via **short‑lived signed URLs**; tampered signature rejected (§74)
- Append‑only **audit log** readable and CSV‑exportable by admin; non‑admins blocked (§72, §99)

---

## API surface (all under `/api/v1`)

| Group | Endpoints |
|---|---|
| Auth (§8, §63) | `POST /auth/login` · `POST /auth/verify-otp` · `POST /auth/refresh` · `POST /auth/logout` · `GET /auth/me` |
| Catalog (§10, §11, §35) | `GET /projects` · `GET /projects/{id}` · `GET /projects/{id}/centers` · `GET /centers/{id}` · `GET /assets/check?serial=` |
| Installations (§17–21, §67) | `POST /installations` · `GET /installations` · `GET /installations/{id}` · `PATCH /installations/{id}` · `POST /installations/{id}/submit` · `GET /installations/{id}/timeline` · `GET /installations/{id}/compliance` |
| Equipment (§69) | `POST /installations/{id}/equipment` · `PATCH /equipment/{id}` |
| Evidence (§36–41, §68, §74) | `POST /evidence/upload` · `GET /evidence/{id}` · `GET /evidence/file` (signed) · `POST /evidence/{id}/replace` · `DELETE /evidence/{id}` |
| Issues (§42, §43, §70) | `POST /issues` · `GET /issues/{id}` · `PATCH /issues/{id}` |
| Sync (§49, §50, §63) | `POST /sync/session` · `POST /sync/acknowledge` (upload via `POST /evidence/upload` with `batch_id`) |
| Admin (§72, §99, §116) | `GET/POST /admin/users` · `PATCH /admin/users/{id}` · `GET /admin/config` · `PUT /admin/config/{key}` · `GET /admin/audit` (`?export=csv`) · `GET /admin/rbac` |

### Cross‑cutting rules implemented

- **Idempotency** — `Idempotency-Key` header (generic replay table) and `client_uuid` on create/upload/submit. §64, §113.
- **Audit by design** — every state change writes an `AuditEvent`; there is no update/delete path for that table. §71, §99.
- **Non‑destructive evidence** — replacement stores the old version in `evidence_versions` with its reason. §41.
- **Signed URLs** — evidence bytes are only reachable through an HMAC‑signed, expiring URL. §74.
- **Server‑side RBAC** — role → permission matrix in `app/security.py` (`GET /api/v1/admin/rbac` to view). §72.
- **Configurable, not hard‑coded** — geofence, photo limits, compliance weights, etc. in `app_config`, editable via `PUT /admin/config/{key}`. §95, §116.
- **Referential integrity** — FKs enforced (SQLite `PRAGMA foreign_keys=ON`); unique installation ids, unique unit numbering per installation. §98.

---

## PostgreSQL / Docker (pilot shape, §62)

```powershell
# with Docker Desktop running
docker compose up --build
```

Brings up `api` + `postgres` + `minio`. Set `CPM_JWT_SECRET` and `CPM_EXPOSE_OTP=false` for anything shared.
For a non‑Docker Postgres, install the extra driver and point the URL at your instance:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-postgres.txt
$env:CPM_DATABASE_URL = "postgresql+psycopg://cpm:cpm@localhost:5432/cpm"
.\.venv\Scripts\python.exe -m uvicorn app.main:app
```

Tables are created on startup via `Base.metadata.create_all`. For real deployments, generate
Alembic migrations from these models before first release (§122 "database migrations are defined").

---

## Not in this build (deliberately)

- Alembic migration files (models are migration‑ready; `create_all` is used for dev)
- A real MinIO/S3 `Storage` implementation (interface is in `app/storage.py`, swap the class)
- Chunked/resumable upload transport (§54) — current upload is a single multipart request with idempotency
- Push/email notifications (§90), observability stack (§89), rate limiting
- The React CPM Portal (§61) — it consumes this same API

## Layout

```
app/
├── main.py            app wiring, exception handlers, router mounts
├── config.py          env-driven settings (CPM_* )
├── database.py        engine / session / Base
├── models.py          SQLAlchemy model — §65–71
├── schemas.py         Pydantic request/response contracts — §64
├── security.py        JWT, bcrypt, RBAC matrix + require() dependency — §72, §73
├── storage.py         object storage interface + local impl + signed URLs — §48, §74
├── compliance.py      evidence-compliance engine (configurable weights) — §19, §95
├── audit.py           append-only audit writer — §71, §99
├── ids.py             INS-YYYY-NNNNNN allocator + token ids
├── serialize.py       ORM → response dicts (fresh signed URL per read)
├── deps.py            fetch-or-404, view-permission checks, idempotency replay
├── seed.py            demo projects / centers / users / asset registry / config
└── routers/           auth · catalog · installations · evidence · issues · sync · admin
smoke_test.py          end-to-end proof (in-process, no network)
run.ps1                venv + deps + smoke test + serve
Dockerfile / docker-compose.yml
```
