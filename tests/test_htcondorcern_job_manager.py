# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for the CERN HTCondor job manager."""

from unittest import mock

import pytest

classad = pytest.importorskip("classad")
pytest.importorskip("htcondor")

from reana_job_controller import htcondorcern_job_manager  # noqa: E402


@pytest.fixture
def manager_dependencies():
    """Patch the heavy dependencies of the HTCondor manager constructor."""
    mock_workflow = mock.MagicMock()
    mock_workflow.get_full_workflow_name.return_value = "wf"
    with mock.patch.object(
        htcondorcern_job_manager.HTCondorJobManagerCERN,
        "_get_workflow",
        return_value=mock_workflow,
    ), mock.patch.object(htcondorcern_job_manager, "initialize_krb5_token"):
        yield


@pytest.fixture
def captured_job_ad(manager_dependencies):
    """Patch ``execute()``'s side-effecting helpers and capture the job_ad.

    Returns a builder ``submit(**kwargs)`` that constructs the manager
    with the given kwargs, calls ``execute()``, and returns the
    ``classad.ClassAd`` that the manager would have sent to the schedd.
    """
    captured = {}

    def fake_executor_submit(_fn, job_ad):
        captured["job_ad"] = job_ad
        future = mock.MagicMock()
        future.result.return_value = "cluster123"
        return future

    fake_app = mock.MagicMock()
    fake_app.htcondor_executor.submit.side_effect = fake_executor_submit

    Manager = htcondorcern_job_manager.HTCondorJobManagerCERN
    with mock.patch.object(
        htcondorcern_job_manager, "current_app", fake_app
    ), mock.patch.object(htcondorcern_job_manager.os, "chdir"), mock.patch.object(
        Manager, "_format_arguments", return_value="echo|base64 -d"
    ), mock.patch.object(
        Manager, "_format_env_vars", return_value=""
    ), mock.patch.object(
        Manager, "_get_input_files", return_value=""
    ), mock.patch.object(
        Manager, "before_execution"
    ), mock.patch.object(
        Manager, "create_job_in_db"
    ):

        def build_and_execute(**kwargs):
            captured.clear()
            base = dict(
                docker_img="img",
                cmd="ls",
                env_vars={},
                workflow_uuid="uuid",
                workflow_workspace="/data",
                job_name="job",
                htcondor_max_runtime="3600",
            )
            base.update(kwargs)
            manager = Manager(**base)
            manager.execute()
            return captured["job_ad"]

        yield build_and_execute


# --- constructor wiring -------------------------------------------------------


def test_constructor_stores_htcondor_request_attributes(manager_dependencies):
    """Constructor must store the four new HTCondor request attributes."""
    manager = htcondorcern_job_manager.HTCondorJobManagerCERN(
        docker_img="img",
        cmd="ls",
        env_vars={},
        workflow_uuid="uuid",
        workflow_workspace="/data",
        job_name="job",
        htcondor_request_cpus="4",
        htcondor_request_memory="4000",
        htcondor_request_disk="100000",
        htcondor_requirements='(Arch =?= "aarch64")',
    )
    assert manager.htcondor_request_cpus == "4"
    assert manager.htcondor_request_memory == "4000"
    assert manager.htcondor_request_disk == "100000"
    assert manager.htcondor_requirements == '(Arch =?= "aarch64")'


def test_constructor_defaults_htcondor_request_attributes_to_empty(
    manager_dependencies,
):
    """When unset, the four new HTCondor request attributes default to empty."""
    manager = htcondorcern_job_manager.HTCondorJobManagerCERN(
        docker_img="img",
        cmd="ls",
        env_vars={},
        workflow_uuid="uuid",
        workflow_workspace="/data",
        job_name="job",
    )
    assert manager.htcondor_request_cpus == ""
    assert manager.htcondor_request_memory == ""
    assert manager.htcondor_request_disk == ""
    assert manager.htcondor_requirements == ""


# --- job_ad mapping in execute() ----------------------------------------------


def test_execute_sets_request_cpus_as_int(captured_job_ad):
    job_ad = captured_job_ad(htcondor_request_cpus="4")
    assert int(job_ad["RequestCpus"]) == 4


def test_execute_converts_request_memory_to_mib(captured_job_ad):
    job_ad = captured_job_ad(htcondor_request_memory="4 GB")
    assert int(job_ad["RequestMemory"]) == 4096


def test_execute_rounds_up_request_memory(captured_job_ad):
    """A ``1 KB`` request must not silently become ``0`` MiB."""
    job_ad = captured_job_ad(htcondor_request_memory="1 KB")
    assert int(job_ad["RequestMemory"]) == 1


def test_execute_converts_request_disk_to_kib(captured_job_ad):
    job_ad = captured_job_ad(htcondor_request_disk="10 GB")
    assert int(job_ad["RequestDisk"]) == 10485760


def test_execute_sets_requirements_as_classad_exprtree(captured_job_ad):
    job_ad = captured_job_ad(htcondor_requirements='(Arch =?= "aarch64")')
    expr = job_ad["Requirements"]
    assert isinstance(expr, classad.ExprTree)
    rendered = str(expr)
    # Asserting on stable fragments rather than exact normal form, since
    # classad's str() can vary in spacing/case across library versions.
    assert "Arch" in rendered
    assert "=?=" in rendered
    assert "aarch64" in rendered


def test_execute_omits_request_attrs_when_absent(captured_job_ad):
    """Absent fields must not appear in the produced ClassAd."""
    job_ad = captured_job_ad()
    assert "RequestCpus" not in job_ad
    assert "RequestMemory" not in job_ad
    assert "RequestDisk" not in job_ad
    assert "Requirements" not in job_ad
