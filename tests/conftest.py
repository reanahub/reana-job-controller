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
def mocked_job():
    """Mock existing job."""
    job_id = str(uuid.uuid4())
    JOB_DB[job_id] = MagicMock()
    return job_id


@pytest.fixture(scope="module")
def base_app(tmp_shared_volume_path):
    """Flask application fixture."""
    config_mapping = {
        "SERVER_NAME": "localhost:5000",
        "SECRET_KEY": "SECRET_KEY",
        "TESTING": True,
        "SHARED_VOLUME_PATH": tmp_shared_volume_path,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///testdb.db",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "ORGANIZATIONS": ["default"],
    }
    app_ = create_app(config_mapping=config_mapping)
    return app_
