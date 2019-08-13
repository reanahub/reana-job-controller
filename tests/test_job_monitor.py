# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller Job Monitor tests."""

import mock
import pytest

from reana_job_controller.job_monitor import (JobMonitorHTCondorCERN,
                                              JobMonitorKubernetes)


def test_if_singelton():
    """Test if job monitor classes are singelton."""
    with mock.patch("reana_job_controller.job_monitor."
                    "threading") as threading:
        first_k8s_instance = JobMonitorKubernetes()
        second_k8s_instance = JobMonitorKubernetes()
        assert first_k8s_instance is second_k8s_instance
        first_htc_instance = JobMonitorHTCondorCERN()
        second_htc_instance = JobMonitorHTCondorCERN()
        assert first_htc_instance is second_htc_instance
