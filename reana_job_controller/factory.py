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

from reana_job_controller import config
from reana_job_controller.spec import build_openapi_spec


def shutdown_session(response_or_exc):
    """Close session and remove all DB connections."""
    db_engine.dispose()


def create_app(config_mapping=None):
    """Create REANA-Job-Controller application."""
    logging.basicConfig(level=REANA_LOG_LEVEL, format=REANA_LOG_FORMAT)
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
    app.teardown_request(shutdown_session)

    # Close session on app teardown
    app.teardown_appcontext(shutdown_session)

    return app
