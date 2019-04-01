# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller application factory."""

import logging
import threading

from flask import Flask
from reana_commons.config import REANA_LOG_FORMAT, REANA_LOG_LEVEL

from reana_job_controller import config
from reana_job_controller.k8s import start_watch_jobs_thread
from reana_job_controller.spec import build_openapi_spec


def create_app(JOB_DB, watch_jobs=True):
    """Create REANA-Job-Controller application."""
    logging.basicConfig(
        level=REANA_LOG_LEVEL,
        format=REANA_LOG_FORMAT
    )
    app = Flask(__name__)
    app.secret_key = "mega secret key"
    app.config.from_object(config)
    with app.app_context():
        app.config['OPENAPI_SPEC'] = build_openapi_spec()

    from reana_job_controller.rest import blueprint  # noqa
    app.register_blueprint(blueprint, url_prefix='/')

    if watch_jobs:
        start_watch_jobs_thread(JOB_DB)

    return app
