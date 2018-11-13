# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Pytest configuration for REANA-Job-Controller."""

from __future__ import absolute_import, print_function

import uuid

import pytest
from mock import MagicMock

from reana_job_controller.factory import create_app
from reana_job_controller.job_db import JOB_DB


@pytest.fixture()
def app():
    """Test application."""
    app = create_app(JOB_DB, watch_jobs=False)
    with app.app_context():
        yield app


@pytest.fixture()
def mocked_job():
    """Mock existing job."""
    job_id = str(uuid.uuid4())
    JOB_DB[job_id] = MagicMock()
    return job_id
