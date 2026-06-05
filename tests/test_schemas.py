# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for REANA-Job-Controller marshmallow schemas."""

from unittest import mock

import pytest
from marshmallow import ValidationError
from reana_commons.job_utils import serialise_job_command

from reana_job_controller.schemas import JobRequest, htcondor_quantity_to_unit

BASE_JOB_REQUEST = {
    "job_name": "job",
    "workflow_workspace": "/data",
    "workflow_uuid": "uuid",
    "docker_img": "img",
    "cmd": serialise_job_command("ls"),
    "kubernetes_job_timeout": 10,
}


@pytest.fixture(autouse=True)
def _kubernetes_timeout_env():
    """Patch the timeout config so the pre_load hook accepts our payload."""
    with mock.patch(
        "reana_job_controller.schemas.REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT", "60"
    ), mock.patch(
        "reana_job_controller.schemas.REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT",
        "3600",
    ):
        yield


def test_htcondor_request_cpus_accepts_positive_int_string():
    """Positive integer strings are accepted for htcondor_request_cpus."""
    loaded = JobRequest().load(dict(BASE_JOB_REQUEST, htcondor_request_cpus="4"))
    assert loaded["htcondor_request_cpus"] == "4"


@pytest.mark.parametrize("bad_value", ["0", "-1", "1.5", "4 GB", "abc", " "])
def test_htcondor_request_cpus_rejects_invalid(bad_value):
    """Non-positive-integer strings are rejected for htcondor_request_cpus."""
    payload = dict(BASE_JOB_REQUEST, htcondor_request_cpus=bad_value)
    with pytest.raises(ValidationError) as exc:
        JobRequest().load(payload)
    assert "htcondor_request_cpus" in exc.value.messages


@pytest.mark.parametrize(
    "field",
    ["htcondor_request_memory", "htcondor_request_disk"],
)
@pytest.mark.parametrize(
    "value",
    ["4096", "4GB", "4 GB", "4 gb", "10TB", "10 TB"],
)
def test_htcondor_request_quantity_field_accepts_valid(field, value):
    """Valid quantity strings are accepted for memory/disk."""
    loaded = JobRequest().load(dict(BASE_JOB_REQUEST, **{field: value}))
    assert loaded[field] == value


@pytest.mark.parametrize(
    "field",
    ["htcondor_request_memory", "htcondor_request_disk"],
)
@pytest.mark.parametrize(
    "bad_value",
    ["0", "-1", "1.5GB", "4Gi", "4 XB", "GB", " ", "abc"],
)
def test_htcondor_request_quantity_field_rejects_invalid(field, bad_value):
    """Invalid quantity strings are rejected for memory/disk."""
    payload = dict(BASE_JOB_REQUEST, **{field: bad_value})
    with pytest.raises(ValidationError) as exc:
        JobRequest().load(payload)
    assert field in exc.value.messages


@pytest.mark.parametrize(
    "field",
    [
        "htcondor_request_cpus",
        "htcondor_request_memory",
        "htcondor_request_disk",
        "htcondor_requirements",
    ],
)
def test_htcondor_field_absence_is_allowed(field):
    """Omitting the new htcondor_* fields is always valid."""
    payload = dict(BASE_JOB_REQUEST)
    payload.pop(field, None)
    JobRequest().load(payload)


def test_htcondor_requirements_accepts_valid_classad_expression():
    """A valid ClassAd expression passes the htcondor_requirements validator."""
    pytest.importorskip("classad")
    payload = dict(
        BASE_JOB_REQUEST,
        htcondor_requirements='(Arch =?= "aarch64")',
    )
    loaded = JobRequest().load(payload)
    assert loaded["htcondor_requirements"] == '(Arch =?= "aarch64")'


def test_htcondor_requirements_rejects_invalid_classad_expression():
    """An unparseable ClassAd expression is rejected with a clear message."""
    pytest.importorskip("classad")
    payload = dict(
        BASE_JOB_REQUEST,
        htcondor_requirements="(Arch =?= ",
    )
    with pytest.raises(ValidationError) as exc:
        JobRequest().load(payload)
    assert "htcondor_requirements" in exc.value.messages


@pytest.mark.parametrize(
    "value, default_unit, expected",
    [
        # No suffix: value is already in default_unit.
        ("4096", "M", 4096),
        ("1000", "K", 1000),
        # Suffix matches default_unit.
        ("4096MB", "M", 4096),
        ("4096 MB", "M", 4096),
        ("1000KB", "K", 1000),
        # Larger unit converts up (binary multipliers).
        ("4GB", "M", 4096),
        ("4 GB", "M", 4096),
        ("4gb", "M", 4096),
        ("10GB", "K", 10485760),
        ("10 GB", "K", 10485760),
        ("1TB", "G", 1024),
        # Smaller unit divides down for exact multiples.
        ("2048KB", "M", 2),
        # Smaller unit rounds UP for non-exact multiples: a user request
        # must never be silently down-converted to a smaller value.
        ("1 KB", "M", 1),
        ("1KB", "M", 1),
        ("1536 KB", "M", 2),
        # 1025 MiB = 1.0009... GiB, rounds up to 2 GiB.
        ("1025 M", "G", 2),
    ],
)
def test_htcondor_quantity_to_unit_conversions(value, default_unit, expected):
    """The conversion helper produces correct integer counts."""
    assert htcondor_quantity_to_unit(value, default_unit) == expected


@pytest.mark.parametrize(
    "bad_value",
    ["0", "-1", "1.5GB", "4Gi", "4 XB", "GB", "", " ", "abc"],
)
def test_htcondor_quantity_to_unit_rejects_invalid(bad_value):
    """Invalid quantity strings raise ValueError from the helper."""
    with pytest.raises(ValueError):
        htcondor_quantity_to_unit(bad_value, "M")
