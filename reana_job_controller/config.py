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
from reana_job_controller.htcondorvc3_job_manager import \
    HTCondorJobManagerVC3

MAX_JOB_RESTARTS = 3
"""Number of retries for a job before considering it as failed."""

SHARED_VOLUME_PATH_ROOT = os.getenv('SHARED_VOLUME_PATH_ROOT', '/var/reana')
"""Root path of the shared volume ."""

COMPUTE_BACKENDS = {
    'kubernetes': KubernetesJobManager,
    'htcondorcern': HTCondorJobManagerCERN,
    'htcondorvc3' : HTCondorJobManagerVC3
}
"""Supported job compute backends and corresponding management class."""

DEFAULT_COMPUTE_BACKEND = 'htcondorvc3'
"""Default job compute backend."""

MULTIPLE_COMPUTE_BACKENDS = os.getenv('MULTIPLE_COMPUTE_BACKENDS', False)
"""Allow multiple job compute backends."""

JOB_HOSTPATH_MOUNTS = []
"""List of tuples composed of name and path to create hostPath's inside jobs.

This configuration should be used only when one knows for sure that the
specified locations exist in all the cluster nodes.

For example, if you are running REANA on Minikube with a single VM you would
have to mount in Minikube the volume you want to be attached to every job:

.. code-block::

    $ minikube mount /usr/local/share/mydata:/mydata

And add the following configuration to REANA-Job-Controller:

.. code-block::

    JOB_HOSTPATH_MOUNTS = [
        ('mydata', '/mydata'),
    ]

This way all jobs will have ``/mydata`` mounted with the content of
``/usr/local/share/mydata`` in the host machine.
"""
