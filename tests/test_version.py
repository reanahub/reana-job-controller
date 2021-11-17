# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller tests."""

from __future__ import absolute_import, print_function


def test_version():
    """Test version import."""
    from reana_job_controller import __version__

    assert __version__
