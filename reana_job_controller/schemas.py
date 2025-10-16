#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Job Controller models."""

from marshmallow import Schema, fields, ValidationError, pre_load
from reana_commons.job_utils import deserialise_job_command

from reana_job_controller.config import (
    REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT,
    REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT,
)


class Job(Schema):
    """Job model."""

    cmd = fields.Str(required=True)
    docker_img = fields.Str(required=True)
    job_id = fields.Str(required=True)
    max_restart_count = fields.Int(required=True)
    restart_count = fields.Int(required=True)
    status = fields.Str(required=True)
    cvmfs_mounts = fields.String(missing="")


class JobRequest(Schema):
    """Job request model."""

    job_name = fields.Str(required=True)
    workflow_workspace = fields.Str(required=True)
    workflow_uuid = fields.Str(required=True)
    cmd = fields.Function(
        missing="", deserialize=deserialise_job_command, type="string"
    )
    prettified_cmd = fields.Str(missing="")
    docker_img = fields.Str(required=True)
    cvmfs_mounts = fields.String(missing="")
    env_vars = fields.Dict(missing={})
    shared_file_system = fields.Bool(missing=True)
    compute_backend = fields.Str(required=False)
    kerberos = fields.Bool(required=False)
    voms_proxy = fields.Bool(required=False)
    rucio = fields.Bool(required=False)
    kubernetes_uid = fields.Int(required=False)
    kubernetes_memory_limit = fields.Str(required=False)
    kubernetes_queue = fields.Str(required=False)
    kubernetes_job_timeout = fields.Int(required=False)
    unpacked_img = fields.Bool(required=False)
    htcondor_max_runtime = fields.Str(required=False)
    htcondor_accounting_group = fields.Str(required=False)
    slurm_partition = fields.Str(required=False)
    slurm_time = fields.Str(required=False)
    c4p_cpu_cores = fields.Str(required=False)
    c4p_memory_limit = fields.Str(required=False)
    c4p_additional_requirements = fields.Str(required=False)

    @pre_load
    def set_kubernetes_job_timeout(self, in_data, **kwargs):
        """Set kubernetes_job_timeout to a default value if not provided and validate the value.

        Method receives the whole data dictionary but operates *only* on kubernetes_job_timeout.
        Updated dictionary is returned.
        """
        if "kubernetes_job_timeout" not in in_data:
            try:
                in_data["kubernetes_job_timeout"] = int(
                    REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT
                )
            except (ValueError, TypeError):
                raise ValidationError(
                    "Default value of kubernetes_job_timeout is not an integer. "
                    f"Provided value is '{REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT}'. "
                    "Please contact the administrator."
                )

        job_timeout = in_data["kubernetes_job_timeout"]

        try:
            job_timeout = int(job_timeout)
        except (ValueError, TypeError):
            raise ValidationError(
                f"kubernetes_job_timeout must be an integer. Provided value is '{job_timeout}'."
            )

        if job_timeout <= 0:
            raise ValidationError(
                "kubernetes_job_timeout must be greater than 0."
                f"Provided value is {job_timeout}."
            )

        try:
            max_value = int(REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT)
        except (ValueError, TypeError):
            raise ValidationError(
                "Max value for kubernetes_job_timeout is not an integer. "
                f"Provided value is '{REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT}'. "
                "Please contact the administrator."
            )

        if job_timeout > max_value:
            raise ValidationError(
                f"kubernetes_job_timeout exceeds maximum allowed value of {max_value} seconds. "
                f"Provided value is {job_timeout} seconds."
            )

        in_data["kubernetes_job_timeout"] = job_timeout
        return in_data
