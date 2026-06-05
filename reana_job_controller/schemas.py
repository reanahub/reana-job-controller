#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA Job Controller models."""

import logging
import re

from marshmallow import Schema, fields, ValidationError, pre_load
from reana_commons.job_utils import deserialise_job_command

from reana_job_controller.config import (
    REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT,
    REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT,
)

try:
    import classad as _classad
except ImportError:
    # `classad` ships with the `htcondor` extras. In a correctly-built
    # job-controller image this import must succeed. We do not fail at
    # module load time so that test environments and non-HTCondor builds
    # can still import this module, but we log a warning so misbuilt
    # production images leave an obvious breadcrumb.
    _classad = None
    logging.getLogger(__name__).warning(
        "classad library is not available; htcondor_requirements "
        "expressions will not be validated at the schema layer. Expected "
        "only in test environments and non-HTCondor builds."
    )

_POSITIVE_INTEGER_RE = re.compile(r"^[1-9]\d*$")

HTCONDOR_QUANTITY_RE = re.compile(
    r"^(?P<value>[1-9]\d*)\s*(?P<unit>K|KB|M|MB|G|GB|T|TB)?$",
    re.IGNORECASE,
)

# HTCondor documents binary multipliers; both `K` and `KB` mean 1024 bytes,
# `M`/`MB` mean 1024**2 bytes, and so on. There is no decimal "KB = 1000"
# interpretation in the HTCondor manual.
HTCONDOR_UNIT_BYTES = {
    "K": 1024,
    "KB": 1024,
    "M": 1024**2,
    "MB": 1024**2,
    "G": 1024**3,
    "GB": 1024**3,
    "T": 1024**4,
    "TB": 1024**4,
}


def htcondor_quantity_to_unit(value, default_unit):
    """Convert an HTCondor quantity string to an integer in ``default_unit``.

    HTCondor's submit-file syntax for ``RequestMemory`` and ``RequestDisk``
    accepts a positive integer with an optional ``K|KB|M|MB|G|GB|T|TB``
    suffix (case-insensitive). When the suffix is omitted, REANA falls back
    to ``default_unit``: ``"M"`` for memory (matching ``RequestMemory``'s
    native unit) and ``"K"`` for disk (matching ``RequestDisk``'s).

    Conversion always rounds up. Using a smaller suffix than the native
    unit (for example ``"1 KB"`` against the ``M`` native unit) yields at
    least ``1``: a user request must never be silently down-converted to
    zero or to a smaller value than asked for. ``"1536 KB"`` becomes
    ``2`` MiB, not ``1``.

    :param value: User-supplied quantity, e.g. ``"4 GB"`` or ``"4096"``.
    :param default_unit: One of the keys of :data:`HTCONDOR_UNIT_BYTES`,
        used when ``value`` has no explicit suffix.
    :returns: Integer count of ``default_unit`` units, rounded up.
    :raises ValueError: when ``value`` does not match the accepted format.
    """
    match = HTCONDOR_QUANTITY_RE.match(value)
    if not match:
        raise ValueError(
            f"Invalid HTCondor quantity {value!r}: "
            "expected a positive integer with optional K/KB/M/MB/G/GB/T/TB "
            "suffix."
        )
    amount = int(match.group("value"))
    unit = match.group("unit")
    unit = unit.upper() if unit else default_unit
    bytes_value = amount * HTCONDOR_UNIT_BYTES[unit]
    divisor = HTCONDOR_UNIT_BYTES[default_unit]
    # Ceiling division to avoid silently under-requesting.
    return (bytes_value + divisor - 1) // divisor


def _validate_positive_integer_string(field_name):
    """Build a marshmallow validator for positive-integer string fields."""

    def _validate(value):
        if value in (None, ""):
            return
        if not _POSITIVE_INTEGER_RE.match(value):
            raise ValidationError(
                f"{field_name} must be a positive integer, got {value!r}."
            )

    return _validate


def _validate_htcondor_quantity_string(field_name, default_unit):
    """Build a marshmallow validator for HTCondor quantity-string fields.

    Accepts ``"<positive int>[ <K|KB|M|MB|G|GB|T|TB>]"`` (case-insensitive).
    The conversion result is discarded here; the manager re-runs the same
    conversion when building the job_ad, so any error surfaces as a clean
    400 with the original field name and value.
    """

    def _validate(value):
        if value in (None, ""):
            return
        try:
            htcondor_quantity_to_unit(value, default_unit)
        except ValueError as exc:
            raise ValidationError(f"{field_name}: {exc}")

    return _validate


def _validate_classad_expression(value):
    """Validate that the value can be parsed as an HTCondor ClassAd expression.

    No-op when the ``classad`` library is not importable. The
    module-load-time warning above flags this state in production logs.
    The HTCondor manager submission path imports ``classad`` at module
    level, so a job-controller environment that lacks ``classad`` cannot
    submit HTCondor jobs at all, regardless of whether schema validation
    runs.
    """
    if value in (None, ""):
        return
    if _classad is None:
        return
    try:
        _classad.ExprTree(value)
    except (SyntaxError, RuntimeError, ValueError) as exc:
        raise ValidationError(
            f"htcondor_requirements is not a valid ClassAd expression: {exc}"
        )


class Job(Schema):
    """Job model."""

    cmd = fields.Str(required=True)
    docker_img = fields.Str(required=True)
    job_id = fields.Str(required=True)
    max_restart_count = fields.Int(required=True)
    restart_count = fields.Int(required=True)
    status = fields.Str(required=True)
    cvmfs_mounts = fields.String(load_default="")


class JobRequest(Schema):
    """Job request model."""

    job_name = fields.Str(required=True)
    workflow_workspace = fields.Str(required=True)
    workflow_uuid = fields.Str(required=True)
    cmd = fields.Function(
        serialize=lambda obj: "",
        deserialize=deserialise_job_command,
        load_default="",
        metadata={"type": "string"},
    )
    prettified_cmd = fields.Str(load_default="")
    docker_img = fields.Str(required=True)
    cvmfs_mounts = fields.String(load_default="")
    env_vars = fields.Dict(load_default={})
    shared_file_system = fields.Bool(load_default=True)
    compute_backend = fields.Str(required=False)
    kerberos = fields.Bool(required=False)
    voms_proxy = fields.Bool(required=False)
    rucio = fields.Bool(required=False)
    kubernetes_uid = fields.Int(required=False)
    kubernetes_cpu_request = fields.Str(required=False)
    kubernetes_cpu_limit = fields.Str(required=False)
    kubernetes_memory_request = fields.Str(required=False)
    kubernetes_memory_limit = fields.Str(required=False)
    kubernetes_job_timeout = fields.Int(required=False)
    unpacked_img = fields.Bool(required=False)
    htcondor_max_runtime = fields.Str(required=False)
    htcondor_accounting_group = fields.Str(required=False)
    htcondor_request_cpus = fields.Str(
        required=False,
        validate=_validate_positive_integer_string("htcondor_request_cpus"),
    )
    htcondor_request_memory = fields.Str(
        required=False,
        validate=_validate_htcondor_quantity_string("htcondor_request_memory", "M"),
    )
    htcondor_request_disk = fields.Str(
        required=False,
        validate=_validate_htcondor_quantity_string("htcondor_request_disk", "K"),
    )
    htcondor_requirements = fields.Str(
        required=False,
        validate=_validate_classad_expression,
    )
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
