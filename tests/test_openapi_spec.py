# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller tests."""

from __future__ import absolute_import, print_function

import json
import os

from swagger_spec_validator.validator20 import validate_json


def test_openapi_spec():
    """Test OpenAPI spec validation."""

    current_dir = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(current_dir, '../docs/openapi.json')) as f:
        reana_job_controller_spec = json.load(f)

    validate_json(reana_job_controller_spec, 'schemas/v2.0/schema.json')
