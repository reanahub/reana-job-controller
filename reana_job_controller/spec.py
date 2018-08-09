#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017 CERN.
#
# REANA is free software; you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# REANA is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# REANA; if not, write to the Free Software Foundation, Inc., 59 Temple Place,
# Suite 330, Boston, MA 02111-1307, USA.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization or
# submit itself to any jurisdiction.

"""OpenAPI generator."""

from apispec import APISpec
from flask import current_app

from reana_job_controller.schemas import Job, JobRequest


def build_openapi_spec():
    """Create OpenAPI definition."""
    spec = APISpec(
        title='reana-job-controller',
        version='0.0.1',
        info=dict(
            description='REANA Job Controller API'
        ),
        plugins=[
            'apispec.ext.flask',
            'apispec.ext.marshmallow',
        ]
    )

    # Add marshmallow models to specification
    spec.definition('Job', schema=Job)
    spec.definition('JobRequest', schema=JobRequest)

    # Collect OpenAPI docstrings from Flask endpoints
    for key in current_app.view_functions:
        if key != 'static' and key != 'get_openapi_spec':
            spec.add_path(view=current_app.view_functions[key])

    return spec.to_dict()
