#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""OpenAPI generator."""

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin
from flask import current_app

from reana_job_controller.schemas import Job, JobRequest
from reana_job_controller.version import __version__


def build_openapi_spec():
    """Create OpenAPI definition."""
    spec = APISpec(
        title="reana-job-controller",
        version=__version__,
        openapi_version="2.0",
        info=dict(description="REANA Job Controller API"),
        plugins=[FlaskPlugin(), MarshmallowPlugin()],
    )

    # Add marshmallow models to specification
    spec.components.schema("Job", schema=Job)
    spec.components.schema("JobRequest", schema=JobRequest)

    # Collect OpenAPI docstrings from Flask endpoints
    for key in current_app.view_functions:
        if key != "static" and key != "get_openapi_spec":
            spec.path(view=current_app.view_functions[key])

    return spec.to_dict()
