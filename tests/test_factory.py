# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Application factory tests."""

from unittest.mock import patch

from reana_commons.config import REANA_WORKFLOW_UMASK

from reana_job_controller.factory import create_app


@patch("reana_job_controller.factory.os.umask")
def test_create_app_sets_workflow_umask(mock_umask):
    """Set the workspace umask once during application initialisation."""
    create_app({"SECRET_KEY": "test-secret", "TESTING": True})

    mock_umask.assert_called_once_with(REANA_WORKFLOW_UMASK)
