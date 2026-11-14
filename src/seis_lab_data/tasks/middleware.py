import asyncio
import logging

import dramatiq
from dramatiq.asyncio import get_event_loop_thread
from redis.asyncio import Redis

from .. import constants
from ..config import (
    get_settings,
    SeisLabDataSettings,
)

logger = logging.getLogger(__name__)


class SeisLabDataSettingsMiddleware(dramatiq.Middleware):
    """
    Dramatiq middleware that stores the settings at worker initialization.
    """

    sld_settings: SeisLabDataSettings | None

    def __init__(self, settings: SeisLabDataSettings):
        self.sld_settings = None

    def after_process_boot(self, broker: dramatiq.Broker):
        """Hook called after a worker process boots.

        Initializes the async Redis client.
        """
        logger.info("Initializing SeisLabData settings...")
        self.sld_settings = get_settings()


class AsyncSqlAlchemyDbMiddleware(dramatiq.Middleware):
    """
    Dramatiq middleware that disposes of the settings' database engine at worker shutdown.
    """

    def after_worker_shutdown(self, broker: dramatiq.Broker, worker: dramatiq.Worker):
        """Dispose of the engine on the event loop that its connections belong to.

        The engine is the one of the settings held by `SeisLabDataSettingsMiddleware`,
        and its connections belong to the event loop of the `AsyncIO` middleware.
        """
        # dramatiq calls `after_*` hooks in reverse order of registration, so this
        # runs before the `AsyncIO` middleware stops its event loop
        settings_middleware = next(
            middleware
            for middleware in broker.middleware
            if isinstance(middleware, SeisLabDataSettingsMiddleware)
        )
        if settings_middleware.sld_settings is None:
            return
        logger.info("Disposing of sqlalchemy engine...")
        get_event_loop_thread().run_coroutine(
            settings_middleware.sld_settings.get_db_engine().dispose()
        )
        logger.debug("sqlalchemy engine disposed.")


class AsyncRedisPubSubMiddleware(dramatiq.Middleware):
    """
    Dramatiq middleware that manages the lifecycle of a redis client for async pub/sub.
    """

    _redis_dsn: str
    redis_client: Redis | None

    def __init__(self, redis_dsn: str):
        self._redis_dsn = redis_dsn
        self.redis_client = None

    def after_process_boot(self, broker: dramatiq.Broker):
        """Hook called after a worker process boots.

        Initializes the async Redis client.
        """
        logger.info("Initializing Redis PubSub client...")
        loop = asyncio.get_event_loop()
        self.redis_client = loop.run_until_complete(Redis.from_url(self._redis_dsn))
        logger.debug("Redis PubSub client initialized.")

    def after_worker_shutdown(self, broker: dramatiq.Broker, worker: dramatiq.Worker):
        """Hook called after a worker process shuts down.

        Closes the async Redis client.
        """
        logger.info("Closing Redis PubSub client...")
        if self.redis_client:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self.redis_client.aclose())
            logger.debug("Redis PubSub client closed.")
        self.redis_client = None


class StaleGeoNodeExportRecoveryMiddleware(dramatiq.Middleware):
    """
    Dramatiq middleware that recovers abandoned GeoNode exports when a worker boots.

    A worker which dies mid-export, e.g. when its container is killed, leaves
    the record under export. Such workers usually come back by being restarted,
    which makes worker boot a good time to look for abandoned exports.
    """

    def after_worker_boot(self, broker: dramatiq.Broker, worker: dramatiq.Worker):
        # the actor is looked up by name, as importing the tasks module here
        # would be circular
        broker.get_actor("recover_stale_geonode_exports").send()


class StaleDiscoveryRecoveryMiddleware(dramatiq.Middleware):
    """
    Dramatiq middleware that recovers abandoned mission discoveries after a worker boots.

    A worker which dies mid-discovery leaves the mission under discovery. Such
    workers usually come back by being restarted. The recovery is enqueued with a
    delay, so that the heartbeat of a discovery abandoned just before the boot has
    become stale by the time the recovery runs.
    """

    def after_worker_boot(self, broker: dramatiq.Broker, worker: dramatiq.Worker):
        # the actor is looked up by name, as importing the tasks module here
        # would be circular
        broker.get_actor("recover_stale_survey_mission_discoveries").send_with_options(
            delay=(
                constants.DISCOVERY_STALE_AFTER_SECONDS
                + constants.DISCOVERY_HEARTBEAT_INTERVAL_SECONDS
            )
            * 1000
        )
