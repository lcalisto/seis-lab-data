# Project overview

Seis-Lab-Data is a web application for managing marine survey data. It provides a catalog of projects, survey missions, and survey-related records, with support for spatial and temporal metadata, validation workflows, and publishing.

## Tech stack

- **Language:** Python 3.12+
- **Web framework:** Starlette with Jinja2 templates and Datastar (HTMX-style SSE interactions)
- **ORM:** SQLModel (SQLAlchemy async under the hood)
- **Database:** PostgreSQL with PostGIS
- **Auth:** Authentik (OpenID Connect via authlib)
- **Task queue:** Dramatiq
- **Pub/sub:** Redis
- **Package manager:** uv
- **Dev environment:** Docker Compose (`docker/compose.dev.yaml`)

## Domain model

The core hierarchy is:

```
Project
  └── SurveyMission (many per project)
        └── SurveyRelatedRecord (many per mission)
              └── RecordAsset (many per record)
```

Each of the three main entities (`Project`, `SurveyMission`, `SurveyRelatedRecord`) has:
- An `owner` field (string, the Authentik user `sub`)
- A `status` enum (`DRAFT`, `PUBLISHED`, plus processing states)
- An `is_valid` flag and a `validation_result` JSONB field
- Spatial extent (`bbox_4326`, PostGIS polygon)
- Temporal extent (`temporal_extent_begin`, `temporal_extent_end`)
- Plain-string `name` and `description` (user data is not localized; only the UI is)

`SurveyRelatedRecord` additionally references lookup tables: `DatasetCategory`, `DomainType`, and `WorkflowStage`. Records can also have self-referential relationships to other records (`SurveyRelatedRecordSelfLink`).

The local `appuser` table is a write-through cache of Authentik user data (`id`, `username`, `email`), upserted on every successful login. It is not a source of truth — Authentik owns identity.

## Source layout

```
src/seis_lab_data/
  auth.py              # OAuth config, get_user(), requires_auth decorator
  authentik.py         # Authentik admin API helper (fetch user by UUID)
  geonode.py           # GeoNode API helpers (upload, execution polling)
  pathpatterns.py      # Path patterns with regexp segments, as used by asset discovery
  config.py            # Settings (pydantic-settings)
  constants.py         # Enums, string constants (ADMIN_ROLE, status enums, etc.)
  errors.py            # SeisLabDataError
  dispatch.py          # Event dispatcher protocol and its Redis implementation
  subscribers.py       # Redis pub/sub subscription and message routing to handlers
  permissions/         # Pure sync permission functions (no DB calls)
  operations/          # Business logic: fetch → check permission → command → emit event
  db/
    models.py          # SQLModel table definitions
    commands/          # Write operations (create, update, delete, upsert)
    queries/           # Read operations (get, list_published, list_accessible, list_*)
    engine.py          # Async engine and session maker
  schemas/             # Pydantic schemas (request/response shapes, IDs, events, messages)
  tasks/               # Dramatiq actors, broker and middleware
  migrations/          # Alembic migrations
  webapp/
    app.py             # Starlette app factory and lifespan
    routes/            # Route handlers (auth, projects, surveymissions, surveyrelatedrecords)
    streamhandlers/    # Handlers turning pub/sub messages into Datastar SSE events
    forms/             # WTForms form definitions
```

## Request flow

Routes → Operations → Permissions + DB queries/commands

- **Routes** extract the user from the session (`get_user(request.session["user"])`), get a DB session from `request.state.settings.get_db_session_maker()`, and call operations.
- **Operations** fetch the relevant DB object first, then call a permission function, then call a command and emit an event.
- **Permissions** are pure sync functions that accept model instances (never IDs) and a user — no DB calls inside.
- **Queries** contain three variants per entity for listing: `list_published_*` (unauthenticated), `list_accessible_*` (authenticated, applies ownership/co-ownership filter), and `list_*` (admin, no filter). The operations layer picks the right one.

## Auth and permissions

Authentication uses Authentik via OIDC. After login the user's `sub`, `email`, `preferred_username`, and `groups` are stored in the Starlette session. The `schemas.User` dataclass holds `id` (the `sub`), `email`, `username`, `roles` (from `groups`), and `active`.

Permission rules:
- **Roles** (in `constants.py`): `ROLE_SYSTEM_ADMIN` (`"system-admin"`, Authentik superusers) and `ROLE_EDITOR` (`"catalog-editor"`, members of the `seis-lab-data-catalog-editors` Authentik group). Both have full access to everything; `permissions/common.py:can_manage_item` is the shared check.
- **Unauthenticated**: read-only access to `PUBLISHED` resources.
- **Authenticated without a role**: read-only access to all resources, including unpublished ones.
- **No self-registration**: user accounts are created by a system admin in Authentik.

## Dev workflow

The dev stack runs via Docker Compose:

```bash
docker compose -f docker/compose.dev.yaml exec -ti webapp uv run <command>
```

Common commands:
- `seis-lab-data db upgrade` — apply migrations
- `seis-lab-data db generate-migration '<description>'` — autogenerate a migration from model changes (always prefer this over hand-writing migrations)

## Async UI processing pattern

State-mutating operations (create, update, delete, validate, publish) are not handled synchronously in the route. Instead, they follow this pipeline:

```
Browser (Datastar) → Route → Dramatiq actor (enqueue) → Redis broker
                  ↑                                           ↓
             SSE stream                            Worker process (actor runs)
                  ↑                                           ↓
           Route (pubsub)  ←─── Redis pub/sub ───  Events published to topic
```

### 1. Page opens an SSE stream, route enqueues the task

Pages that trigger tasks open a long-lived SSE stream when they load (e.g. `survey_related_records:detail_stream`), carrying a request ID generated when the page was rendered. The mutating route receives that same request ID as a query param, enqueues the actor via `.send(...)` and returns immediately.

```python
record_tasks.delete_survey_related_record.send(
    raw_request_id=str(request_id),
    raw_survey_related_record_id=str(survey_related_record_id),
    raw_initiator=json.dumps(dataclasses.asdict(user)),
)
return Response(status_code=200)
```

### 2. Dramatiq actor executes in a worker process

Actors are defined in `tasks/<entity>.py` with `@dramatiq.actor`. Dependencies are injected via custom middleware and decorators (`@decorators.sld_settings`, `@decorators.redis_client`). The actor calls the operations layer, passing it an event dispatcher (`settings.get_event_dispatcher()`). Operations report what happened by calling the dispatcher with typed events from `schemas/events.py` (`ResourceModificationEvent`, `ResourceStatusChangedEvent`, `ValidationEvent`, `DiscoveryEvent`, `ExportEvent`, ...).

```python
await event_dispatcher(
    event_schemas.ResourceModificationEvent(
        initiator=initiator.id,
        resource_type=constants.ResourceType.RECORD,
        resource_id=str(survey_related_record_id),
        request_id=request_id,
        modification=constants.ResourceModification.DELETED,
        succeeded=True,
    )
)
```

`dispatch.RedisEventDispatcher` turns each event into its message (`schemas/messages.py`, discriminated by `type`) and publishes it on the topic of its resource type (`ResourceType.get_topic_name()`, e.g. `survey_related_records`).

### 3. Route relays messages to the browser via SSE

The stream routes subscribe with `subscribers.open_topic_subscription()` and `subscribers.iter_topic_messages()`, which parses each message and hands it to the handler registered for its `type`. Handlers live in `webapp/streamhandlers/` and yield Datastar SSE events: they filter on `resource_id`/`request_id`, then show notifications, patch signals or redirect (often to the same page, to re-render it).

### 4. Datastar updates the DOM

The frontend uses [Datastar](https://data-star.dev/) directives (`data-on:click`, `data-attr`, `data-text`, etc.) on HTML elements. Mutating requests go via `@post(...)`/`@delete(...)` with the CSRF token in a header. The server pushes SSE events that Datastar applies to the page.

### Long-running tasks

Tasks which may take long run in their own queues: `previews`, `thumbnails` and `exports` are consumed by the `long-tasks-worker` service and `discovery` by the `discovery-worker` service (one thread per process, so each process discovers one mission at a time), while the `interactive-worker` service consumes the `default` queue, so they never delay the interactive tasks of the `default` queue. Separate queues alone are not enough for this: all async actors of a worker process share a single event loop, whatever their queue, so it is running in a separate worker service that keeps a task's blocking work (e.g. the blocking file reads of httpx multipart uploads) from stalling the interactive tasks. Discovery pipelines its work within its one message: the walk looks up matched paths in chunks, `discovery_extraction_concurrency` metadata extractions run concurrently, each in a worker process (`anyio.to_process`) so they use several CPU cores (the discovery tests run them in threads instead, by replacing `anyio.to_process.run_sync`, so that they can replace the extractors), and a single writer stores records in batches with SQLAlchemy Core statements (`db/commands/discovery.py:write_discovered_survey_related_records`), bypassing the ORM record operations for speed; its rows must stay equal to those of `operations/surveyrelatedrecords.py:create_survey_related_record`, which a test checks. The previews of the created records are requested per written batch, with `tasks/previews.py:generate_records_previews` taking up to `PREVIEW_BATCH_SIZE` record ids, and at the end of a run `generate_mission_previews` covers the mission's older records still missing previews. A run stops itself after `discovery_time_limit_hours`. While a task works on a record it holds it in a busy status (`UNDER_DERIVATION`, `UNDER_EXPORT`, ...), flipped with `compare_and_set_survey_related_record_status`; records in any status other than `DRAFT`/`PUBLISHED` cannot be updated or deleted.

### Broker setup

`tasks/broker.py` configures a `RedisBroker` with these middleware layers:
- `AsyncIO` — runs actors in an async event loop
- `SeisLabDataSettingsMiddleware` — provides app settings
- `AsyncRedisPubSubMiddleware` — manages the Redis client for pub/sub
- `AsyncSqlAlchemyDbMiddleware` — disposes of the settings' async DB engine at worker shutdown; actors get sessions from `settings.get_db_session_maker()`, whose pool is bounded by the `db_pool_size`, `db_max_overflow` and `db_pool_timeout` settings
- `StaleGeoNodeExportRecoveryMiddleware` — recovers records left under export by a dead worker, at worker boot
- `StaleDiscoveryRecoveryMiddleware` — recovers missions left under discovery by a dead worker, some minutes after worker boot

## Key conventions

- Migrations are always generated by Alembic (`db generate-migration`), never written by hand.
- Avoid single-line or thin wrapper helper functions — inline the logic instead.
- Imports always at the top of the module, never inside functions.
- The `appuser` table is named to avoid colliding with PostgreSQL's reserved `user` keyword.
- All IDs are `NewType` wrappers over `uuid.UUID` or `str` (e.g. `ProjectId`, `UserId`).
