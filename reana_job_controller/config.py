# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Flask application configuration."""

from distutils.util import strtobool
import os
import secrets

from werkzeug.utils import import_string

REANA_DB_CLOSE_POOL_CONNECTIONS = bool(
    strtobool(os.getenv("REANA_DB_CLOSE_POOL_CONNECTIONS", "false"))
)
"""Determine whether to close each database connection when it is returned to the pool."""

SECRET_KEY = os.getenv("REANA_SECRET_KEY", secrets.token_hex())
"""Secret key used for the application user sessions.

A new random key is generated on every start of job-controller, but this is not an
issues as job-controller is never restarted (and thus the secret never changes)
during the execution of a single workflow."""

CACHE_ENABLED = False
"""Determines if jobs caching is enabled."""

DASK_SCHEDULER_URI = os.getenv("DASK_SCHEDULER_URI", "tcp://127.0.0.1:8080")
"""Address of the Dask Scheduler."""

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
    "compute4punch": lambda: import_string(
        "reana_job_controller.compute4punch_job_manager.Compute4PUNCHJobManager"
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
    "compute4punch": lambda: import_string(
        "reana_job_controller.job_monitor.JobMonitorCompute4PUNCH"
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
    "VOMSPROXY_CONTAINER_IMAGE", "docker.io/reanahub/reana-auth-vomsproxy:1.3.1"
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

KUEUE_ENABLED = bool(strtobool(os.getenv("KUEUE_ENABLED", "False")))
"""Whether to use Kueue to manage job execution."""

KUEUE_DEFAULT_QUEUE = os.getenv("KUEUE_DEFAULT_QUEUE", "")
"""Name of the default queue to be used by Kueue."""

REANA_USER_ID = os.getenv("REANA_USER_ID")
"""User UUID of the owner of the workflow."""

C4P_LOGIN_NODE_HOSTNAME = os.getenv("C4P_LOGIN_NODE", "c4p-login.gridka.de")
"""Hostname of C4P login node used for job management via SSH."""

C4P_LOGIN_NODE_PORT = os.getenv("C4P_LOGIN_NODE_PORT", "22")
"""Port of C4P login node."""

C4P_SSH_TIMEOUT = float(os.getenv("C4P_SSH_TIMEOUT", "60"))
"""Seconds to wait for C4P SSH TCP connection."""

C4P_SSH_BANNER_TIMEOUT = float(os.getenv("C4P_SSH_BANNER_TIMEOUT", "60"))
"""Seconds to wait for C4P SSH banner to be presented."""

C4P_SSH_AUTH_TIMEOUT = float(os.getenv("C4P_SSH_AUTH_TIMEOUT", "60"))
"""Seconds to wait for C4P SSH authentication response."""

C4P_CPU_CORES = os.getenv("C4P_CPU_CORES", "8")
"""Number of CPU cores used to run the REANA jobs."""

C4P_MEMORY_LIMIT = os.getenv("C4P_MEMORY_LIMIT", "20000")
"""Maximum amount memory used by the REANA jobs."""

C4P_ADDITIONAL_REQUIREMENTS = os.getenv("C4P_ADDITIONAL_REQUIREMENTS", "")
"""Additional requirements to run the REANA jobs on C4P nodes."""

C4P_REANA_REL_WORKFLOW_PATH = os.getenv(
    "C4P_REANA_REL_WORKFLOW_PATH", "reana/workflows"
)
"""Path relative to the uses home directory of the REANA workflow space on the C4P login node."""
