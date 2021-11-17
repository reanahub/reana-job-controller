#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Job Controller models."""

from marshmallow import Schema, fields, pre_load
from reana_commons.job_utils import deserialise_job_command


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
    cmd = fields.Function(missing="", deserialize=deserialise_job_command)
    prettified_cmd = fields.Str(missing="")
    docker_img = fields.Str(required=True)
    cvmfs_mounts = fields.String(missing="")
    env_vars = fields.Dict(missing={})
    shared_file_system = fields.Bool(missing=True)
    compute_backend = fields.Str(required=False)
    kerberos = fields.Bool(required=False)
    voms_proxy = fields.Bool(required=False)
    kubernetes_uid = fields.Int(required=False)
    kubernetes_memory_limit = fields.Str(required=False)
    unpacked_img = fields.Bool(required=False)
    htcondor_max_runtime = fields.Str(required=False)
    htcondor_accounting_group = fields.Str(required=False)
