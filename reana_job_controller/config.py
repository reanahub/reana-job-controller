# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Flask application configuration."""

import os

from reana_job_controller.kubernetes_job_manager import KubernetesJobManager

MAX_JOB_RESTARTS = 3
"""Number of retries for a job before considering it as failed."""

SHARED_VOLUME_PATH_ROOT = os.getenv('SHARED_VOLUME_PATH_ROOT', '/var/reana')
"""Root path of the shared volume ."""

JOB_BACKENDS = {
    'Kubernetes': KubernetesJobManager
}
"""Supported job backends and corresponding management class."""

DEFAULT_JOB_BACKEND = 'Kubernetes'
"""Default compute backend for job submission."""
