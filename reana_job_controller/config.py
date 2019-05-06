# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Flask application configuration."""

import os

from reana_job_controller.htcondorcern_job_manager import \
    HTCondorJobManagerCERN
from reana_job_controller.kubernetes_job_manager import KubernetesJobManager

MAX_JOB_RESTARTS = 3
"""Number of retries for a job before considering it as failed."""

SHARED_VOLUME_PATH_ROOT = os.getenv('SHARED_VOLUME_PATH_ROOT', '/var/reana')
"""Root path of the shared volume ."""

JOB_BACKENDS = {
    'kubernetes': KubernetesJobManager,
    'htcondorcern': HTCondorJobManagerCERN
}
"""Supported job backends and corresponding management class."""

DEFAULT_JOB_BACKEND = 'kubernetes'
"""Default compute backend for job submission."""

HTCONDOR_SUBMISSION_JOB_IMG = os.getenv('HTCONDOR_SUBMISSION_JOB_IMG',
                                        'batch-team/condorsubmit')
"""Docker image to use for condor job submission."""

HTCONDOR_SUBMITTER_POD_MAX_LIFETIME = 3600
"""Maximum lifetime of HTCondor submitter pod in seconds."""

HTCONDOR_SUBMITTER_POD_CLEANUP_THRESHOLD = 60
"""Seconds to delete HTCondor submitter pod after termination."""
