# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Flask application configuration."""

import os

from reana_commons.config import REANA_COMPONENT_PREFIX

from werkzeug.utils import import_string

SHARED_VOLUME_PATH_ROOT = os.getenv("SHARED_VOLUME_PATH_ROOT", "/var/reana")
"""Root path of the shared volume ."""

COMPUTE_BACKENDS = {
    "kubernetes": lambda: import_string(
        "reana_job_controller.kubernetes_job_manager.KubernetesJobManager"
    ),
    "htcondorcern": lambda: import_string(
        "reana_job_controller.htcondorcern_job_manager.HTCondorJobManagerCERN"
    ),
    "slurmcern": lambda: import_string(
        "reana_job_controller.slurmcern_job_manager.SlurmJobManagerCERN"
    ),
}
"""Supported job compute backends and corresponding management class."""

JOB_MONITORS = {
    "kubernetes": lambda: import_string(
        "reana_job_controller.job_monitor.JobMonitorKubernetes"
    ),
    "htcondorcern": lambda: import_string(
        "reana_job_controller.job_monitor.JobMonitorHTCondorCERN"
    ),
    "slurmcern": lambda: import_string(
        "reana_job_controller.job_monitor.JobMonitorSlurmCERN"
    ),
}
"""Classes responsible for monitoring specific backend jobs"""


DEFAULT_COMPUTE_BACKEND = "kubernetes"
"""Default job compute backend."""

SUPPORTED_COMPUTE_BACKENDS = os.getenv(
    "COMPUTE_BACKENDS", DEFAULT_COMPUTE_BACKEND
).split(",")
"""List of supported compute backends provided as docker build arg."""


VOMSPROXY_CONTAINER_IMAGE = os.getenv(
    "VOMSPROXY_CONTAINER_IMAGE", "docker.io/reanahub/reana-auth-vomsproxy:1.2.0"
)
"""Default docker image of VOMSPROXY sidecar container."""

VOMSPROXY_CONTAINER_NAME = "voms-proxy"
"""Name of VOMSPROXY sidecar container."""

VOMSPROXY_CERT_CACHE_LOCATION = "/vomsproxy_cache/"
"""Directory of voms-proxy certificate cache.

This directory is shared between job & VOMSPROXY container."""

VOMSPROXY_CERT_CACHE_FILENAME = "x509up_proxy"
"""Name of the voms-proxy certificate cache file."""

RUCIO_CONTAINER_IMAGE = os.getenv(
    "RUCIO_CONTAINER_IMAGE", "docker.io/reanahub/reana-auth-rucio:1.1.1"
)
"""Default docker image of RUCIO sidecar container."""

RUCIO_CONTAINER_NAME = "reana-auth-rucio"
"""Name of RUCIO sidecar container."""

RUCIO_CACHE_LOCATION = "/rucio_cache/"
"""Directory of Rucio cache.

This directory is shared between job & Rucio container."""

RUCIO_CFG_CACHE_FILENAME = "rucio.cfg"
"""Name of the RUCIO configuration cache file."""

RUCIO_CERN_BUNDLE_CACHE_FILENAME = "CERN-bundle.pem"
"""Name of the CERN Bundle cache file."""

IMAGE_PULL_SECRETS = os.getenv("IMAGE_PULL_SECRETS", "").split(",")
"""Docker image pull secrets which allow the usage of private images."""

REANA_KUBERNETES_JOBS_MEMORY_LIMIT = os.getenv("REANA_KUBERNETES_JOBS_MEMORY_LIMIT")
"""Maximum default memory limit for user job containers. Exceeding this limit will terminate the container.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-memory.
"""

REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT = os.getenv(
    "REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT"
)
"""Maximum custom memory limit that users can assign to their job containers via
``kubernetes_memory_limit`` in reana.yaml. Exceeding this limit will terminate the container.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-memory.
"""

REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT = os.getenv("REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT")
"""Default timeout for user's job. Exceeding this time will terminate the job.

Please see the following URL for more details
https://kubernetes.io/docs/concepts/workloads/controllers/job/#job-termination-and-cleanup.
"""

REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT = os.getenv(
    "REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT"
)
"""Maximum custom timeout that users can assign to their job.

Please see the following URL for more details
https://kubernetes.io/docs/concepts/workloads/controllers/job/#job-termination-and-cleanup.
"""

SLURM_HEADNODE_HOSTNAME = os.getenv("SLURM_HOSTNAME", "hpc-batch.cern.ch")
"""Hostname of SLURM head-node used for job management via SSH."""

SLURM_HEADNODE_PORT = os.getenv("SLURM_CLUSTER_PORT", "22")
"""Port of SLURM head node."""

SLURM_PARTITION = os.getenv("SLURM_PARTITION", "inf-short")
"""Default slurm partition."""

SLURM_JOB_TIMELIMIT = os.getenv("SLURM_JOB_TIMELIMIT", "60")
"""Default SLURM job timelimit.

Acceptable time formats include "minutes", "minutes:seconds", "hours:minutes:seconds", "days-hours",
"days-hours:minutes" and "days-hours:minutes:seconds". A time limit of zero means that no time limit
will be imposed. Please see the following URL for more details
https://slurm.schedmd.com/sbatch.html (-t, --time)
"""

SLURM_SSH_TIMEOUT = float(os.getenv("SLURM_SSH_TIMEOUT", "60"))
"""Seconds to wait for SLURM SSH TCP connection."""

SLURM_SSH_BANNER_TIMEOUT = float(os.getenv("SLURM_SSH_BANNER_TIMEOUT", "60"))
"""Seconds to wait for SLURM SSH banner to be presented."""

SLURM_SSH_AUTH_TIMEOUT = float(os.getenv("SLURM_SSH_AUTH_TIMEOUT", "60"))
"""Seconds to wait for SLURM SSH authentication response."""

USE_KUEUE = bool(os.getenv("USE_KUEUE", "False"))