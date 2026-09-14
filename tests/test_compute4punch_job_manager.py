# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller Compute4PUNCH Job Manager tests."""

import mock

import pytest

from reana_job_controller import compute4punch_job_manager
from reana_job_controller.compute4punch_job_manager import Compute4PUNCHJobManager
from reana_job_controller.config import C4P_CPU_CORES


@pytest.fixture
def manager(monkeypatch):
    """Create a Compute4PUNCH job manager with external dependencies mocked."""
    monkeypatch.setattr(Compute4PUNCHJobManager, "C4P_HOME_PATH", "")
    monkeypatch.setattr(Compute4PUNCHJobManager, "C4P_WORKSPACE_PATH", "")

    with (
        mock.patch.object(compute4punch_job_manager, "SSHClient"),
        mock.patch.object(
            compute4punch_job_manager,
            "motley_cue_auth_strategy_factory",
        ),
    ):
        return Compute4PUNCHJobManager(
            docker_img="img",
            cmd="ls",
            env_vars={},
            workflow_uuid="uuid",
            workflow_workspace="/reana_workspace",
            job_name="job",
        )


@pytest.mark.parametrize(
    "notification",
    ["Always", "Complete", "Error", "Never", ""],
)
def test_notification_directive_and_recipient_in_jdl(manager, notification):
    """Test notification directive and notification recipient.

    When a notification mode is configured, the corresponding notification
    directive and the notification recipient, i.e. the workflow owner's email,
    are included in the JDL. When no notification mode is configured, both
    the notification directive and the notification recipient are absent
    from the JDL. The ``Never`` notification mode keeps the workflow owner's email
    in the JDL for C4P credential-expiry notifications.
    """
    workflow = mock.MagicMock()
    workflow.get_full_workflow_name.return_value = "workflow"

    with (
        mock.patch.object(
            Compute4PUNCHJobManager,
            "workflow",
            new_callable=mock.PropertyMock,
            return_value=workflow,
        ),
        mock.patch.object(
            Compute4PUNCHJobManager,
            "email_workflow_owner",
            new_callable=mock.PropertyMock,
            return_value="alice.hertzog@example.org",
        ),
    ):
        manager.set_c4p_notification(notification)
        manager._create_c4p_job_description(job_inputs=[])

    command = manager.c4p_connection.exec_command.call_args.args[0]

    if notification:
        assert f"notification = {notification}" in command
        assert "notify_user = alice.hertzog@example.org" in command
    else:
        assert "notification =" not in command
        assert "notify_user =" not in command


@pytest.mark.parametrize(
    "workflow, expected_email",
    [
        (None, None),
        (mock.MagicMock(owner=None), None),
        (mock.MagicMock(owner=mock.MagicMock(email="alice.hertzog@example.org")), "alice.hertzog@example.org"),
    ],
)
def test_retrieve_email_workflow_owner(manager, workflow, expected_email):
    """Return workflow owner email address."""
    with mock.patch.object(
        Compute4PUNCHJobManager,
        "workflow",
        new_callable=mock.PropertyMock,
        return_value=workflow,
    ):
        assert manager.email_workflow_owner == expected_email


@pytest.mark.parametrize(
    "cpu_cores",
    ["2", ""],
)
def test_cpu_in_jdl(manager, cpu_cores):
    """Include CPU request using the configured default when not specified."""
    workflow = mock.MagicMock()
    workflow.get_full_workflow_name.return_value = "workflow"

    with (
        mock.patch.object(
            Compute4PUNCHJobManager,
            "workflow",
            new_callable=mock.PropertyMock,
            return_value=workflow,
        ),
        mock.patch.object(
            Compute4PUNCHJobManager,
            "email_workflow_owner",
            new_callable=mock.PropertyMock,
            return_value=None,
        ),
    ):
        manager.set_c4p_cpu_cores(cpu_cores)
        manager._create_c4p_job_description(job_inputs=[])

    command = manager.c4p_connection.exec_command.call_args.args[0]

    if cpu_cores == "2":
        assert f"request_cpus = {cpu_cores}" in command
    else:
        assert f"request_cpus = {C4P_CPU_CORES}" in command


@pytest.mark.parametrize(
    "gpu_count",
    ["2", ""],
)
def test_gpu_in_jdl(manager, gpu_count):
    """Include or omit GPU request depending on configuration."""
    workflow = mock.MagicMock()
    workflow.get_full_workflow_name.return_value = "workflow"

    with (
        mock.patch.object(
            Compute4PUNCHJobManager,
            "workflow",
            new_callable=mock.PropertyMock,
            return_value=workflow,
        ),
        mock.patch.object(
            Compute4PUNCHJobManager,
            "email_workflow_owner",
            new_callable=mock.PropertyMock,
            return_value=None,
        ),
    ):
        manager.set_c4p_gpu_count(gpu_count)
        manager._create_c4p_job_description(job_inputs=[])

    command = manager.c4p_connection.exec_command.call_args.args[0]

    if gpu_count == "2":
        assert f"request_gpus = {gpu_count}" in command
    else:
        assert "request_gpus =" not in command
