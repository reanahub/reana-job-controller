# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller application factory."""

import logging
from concurrent.futures import ThreadPoolExecutor

from flask import Flask
from reana_commons.config import REANA_LOG_FORMAT, REANA_LOG_LEVEL
from reana_db.database import Session, engine as db_engine
from sqlalchemy import event

from reana_job_controller import config
from reana_job_controller.spec import build_openapi_spec
from reana_job_controller.utils import MultilineFormatter


@event.listens_for(db_engine, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    """Close all the connections before returning them to the connection pool."""
    # Given the current architecture of REANA, job-controller needs to connect to the
    # database in order to, among other things, update the details of jobs. However,
    # it can happen that for long periods of time job-controller does not need to access
    # the database, for example when waiting for long-lasting jobs to finish. During this
    # time, connections that are kept in the pool still consume the available connection
    # slots of PostgreSQL, even though they are not being used. This effectively limits
    # the number of workflows that can run in parallel.
    #
    # There are a few options to avoid this:
    #  - enable external connection pooling with PgBouncer in the Helm chart, so that
    #    many more connections can be opened at the same time
    #  - increase the number of connection slots of PostgreSQL, but this increases the
    #    memory/cpu needed by the database
    #  - close each connection as soon as it is returned to the pool
    #
    # Note that closing connections every time they are returned to the pool means that
    # every new transaction will need to open a connection to the database. This
    # impacts how fast jobs can be spawned, as opening a connection takes quite some time
    # (tens of millisecond). For this reason, connections are not closed by default when
    # they are returned to the pool, but this behaviour can be customised with env
    # variables.
    if config.REANA_DB_CLOSE_POOL_CONNECTIONS:
        connection_record.close()


def shutdown_session(response_or_exc):
    """Close session at the end of each request."""
    Session.close()


def create_app(config_mapping=None):
    """Create REANA-Job-Controller application."""
    handler = logging.StreamHandler()
    handler.setFormatter(MultilineFormatter(REANA_LOG_FORMAT))
    logging.basicConfig(
        level=REANA_LOG_LEVEL, format=REANA_LOG_FORMAT, handlers=[handler]
    )

    app = Flask(__name__)
    app.secret_key = "mega secret key"
    app.session = Session
    app.config.from_object(config)
    if config_mapping:
        app.config.from_mapping(config_mapping)
    if "htcondorcern" in app.config["SUPPORTED_COMPUTE_BACKENDS"]:
        app.htcondor_executor = ThreadPoolExecutor(max_workers=1)
    with app.app_context():
        app.config["OPENAPI_SPEC"] = build_openapi_spec()

    from reana_job_controller.rest import blueprint  # noqa

    app.register_blueprint(blueprint, url_prefix="/")

    # Close session after each request
    app.teardown_appcontext(shutdown_session)

    return app
