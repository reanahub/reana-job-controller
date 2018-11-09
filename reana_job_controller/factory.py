# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller application factory."""

from flask import Flask

from reana_job_controller import config
from reana_job_controller.spec import build_openapi_spec


def create_app():
    """Create REANA-Job-Controller application."""
    app = Flask(__name__)
    app.secret_key = "mega secret key"

    app.config.from_object(config)
    app.config['SERVER_NAME'] = 'localhost:5000'
    with app.app_context():
        app.config['OPENAPI_SPEC'] = build_openapi_spec()

    from reana_job_controller.rest import blueprint  # noqa
    app.register_blueprint(blueprint)

    return app
