# Regulatory Watch — v1

AI-powered regulatory monitoring platform.

## Quick Start

```bash
# Start everything (first time takes ~2 min to build)
make up

# Wait ~30 seconds for services, then run smoke tests
make test
```

## Services

| Service   | URL                           | Description                   |
| --------- | ----------------------------- | ----------------------------- |
| API       | http://localhost:8000         | FastAPI REST API               |
| Docs      | http://localhost:8000/docs    | Swagger UI (auto-generated)    |
| Flower    | http://localhost:5555         | Celery task monitoring         |
| PostgreSQL| localhost:5432                | Database (regwatch/regwatch_secret) |
| Redis     | localhost:6379                | Task broker + cache            |
| Kafka     | localhost:9092                | Message bus                    |

## API Endpoints

### Health
- `GET /health` — API liveness
- `GET /health/db` — PostgreSQL connectivity
- `GET /health/redis` — Redis connectivity

### Domains
- `POST /domains` — Register a new domain
- `GET /domains` — List domains (paginated, filterable by status)
- `GET /domains/{id}` — Get single domain
- `PATCH /domains/{id}` — Update domain
- `DELETE /domains/{id}` — Remove domain

## Makefile Targets

```bash
make up              # Start all services
make down            # Stop all services
make clean           # Stop + remove volumes
make logs            # Tail all logs
make logs-api        # Tail API logs only
make logs-worker     # Tail worker logs only
make migrate         # Run Alembic migrations
make test            # Run smoke tests
make shell           # Shell into API container
make status          # Show container status
```

## Environment Variables

| Variable                  | Default                                              | Description          |
| ------------------------- | ---------------------------------------------------- | -------------------- |
| `DATABASE_URL`            | `postgresql://regwatch:regwatch_secret@db:5432/regwatch` | PostgreSQL connection |
| `REDIS_URL`               | `redis://redis:6379/0`                               | Redis connection      |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:29092`                                        | Kafka broker address  |

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   FastAPI    │    │   Celery    │    │   Flower    │
│   (API)      │    │  (Worker)   │    │ (Monitor)   │
└──────┬───────┘    └──────┬──────┘    └─────────────┘
       │                   │
       ├───────────────────┤
       │                   │
┌──────┴───────┐    ┌──────┴──────┐    ┌─────────────┐
│  PostgreSQL  │    │    Redis    │    │    Kafka    │
│   (Data)     │    │  (Broker)   │    │ (Messages)  │
└──────────────┘    └─────────────┘    └─────────────┘
```

## Project Structure

```
regulation-prj-v1/
├── app/
│   ├── main.py           # FastAPI app, CORS, lifespan
│   ├── config.py          # Settings via pydantic-settings
│   ├── database.py        # Engine, sessions
│   ├── models.py          # Domain, Url, FetchRun, FetchAttempt
│   ├── schemas.py         # API request/response schemas
│   ├── celery_app.py      # Celery + heartbeat task
│   └── routers/
│       ├── health.py      # /health, /health/db, /health/redis
│       └── domains.py     # CRUD /domains
├── alembic/               # Database migrations
├── docker-compose.yml     # 7 services
├── Dockerfile
├── Makefile
└── requirements.txt
```
