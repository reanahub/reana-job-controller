# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
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

KRB5_CONTAINER_IMAGE = os.getenv(
    "KRB5_CONTAINER_IMAGE", "reanahub/reana-auth-krb5:1.0.1"
)
"""Default docker image of KRB5 sidecar container."""

KRB5_CONTAINER_NAME = "krb5"
"""Name of KRB5 sidecar container."""

KRB5_TOKEN_CACHE_LOCATION = "/krb5_cache/"
"""Directory of Kerberos tokens cache, shared between job & KRB5 container. It
should match `default_ccache_name` in krb5.conf.
"""

KRB5_TOKEN_CACHE_FILENAME = "krb5_{}"
"""Name of the Kerberos token cache file."""

KRB5_CONFIGMAP_NAME = os.getenv(
    "REANA_KRB5_CONFIGMAP_NAME", f"{REANA_COMPONENT_PREFIX}-krb5-conf"
)
"""Kerberos configMap name."""

VOMSPROXY_CONTAINER_IMAGE = os.getenv(
    "VOMSPROXY_CONTAINER_IMAGE", "reanahub/reana-auth-vomsproxy:1.0.0"
)
"""Default docker image of VOMSPROXY sidecar container."""

VOMSPROXY_CONTAINER_NAME = "voms-proxy"
"""Name of VOMSPROXY sidecar container."""

VOMSPROXY_CERT_CACHE_LOCATION = "/vomsproxy_cache/"
"""Directory of voms-proxy certificate cache.

This directory is shared between job & VOMSPROXY container."""

VOMSPROXY_CERT_CACHE_FILENAME = "x509up_proxy"
"""Name of the voms-proxy certificate cache file."""

IMAGE_PULL_SECRETS = os.getenv("IMAGE_PULL_SECRETS", "").split(",")
"""Docker image pull secrets which allow the usage of private images."""

REANA_KUBERNETES_JOBS_MEMORY_LIMIT = os.getenv("REANA_KUBERNETES_JOBS_MEMORY_LIMIT")
"""Maximum memory limit for user job containers. Exceeding this limit will terminate the container.

Please see the following URL for possible values
https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/#meaning-of-memory.
"""
