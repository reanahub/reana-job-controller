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
from reana_job_controller.compute4punch_job_manager import (
    Compute4PUNCHJobManager,
)


@pytest.fixture
def manager():
    """Create a Compute4PUNCH job manager with external dependencies mocked."""
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


def test_include_notification(manager):
    """Include notification when configured."""
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
        manager.c4p_notification = "Complete"

        manager._create_c4p_job_description(job_inputs=[])

    command = manager.c4p_connection.exec_command.call_args.args[0]
    assert "notification = Complete" in command


def test_omit_notification(manager):
    """Omit notification when not configured."""
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
        manager.c4p_notification = None

        manager._create_c4p_job_description(job_inputs=[])

    command = manager.c4p_connection.exec_command.call_args.args[0]
    assert "notification =" not in command
    assert "notify_user =" not in command


def test_email_workflow_owner(manager):
    """Return workflow owner email address."""
    workflow = mock.MagicMock()
    workflow.owner_id = "owner-id"

    user = mock.MagicMock()
    user.email = "alice.hertzog@example.org"

    user_query = mock.MagicMock()
    user_query.filter_by.return_value.one_or_none.return_value = user

    with (
        mock.patch.object(
            Compute4PUNCHJobManager,
            "workflow",
            new_callable=mock.PropertyMock,
            return_value=workflow,
        ),
        mock.patch.object(
            compute4punch_job_manager.Session,
            "query",
            return_value=user_query,
        ),
    ):
        assert manager.email_workflow_owner == "alice.hertzog@example.org"


def test_include_email_workflow_owner(manager):
    """Use workflow owner email address as notification recipient."""
    workflow = mock.MagicMock()
    workflow.owner_id = "owner-id"
    workflow.get_full_workflow_name.return_value = "workflow"

    user = mock.MagicMock()
    user.email = "alice.hertzog@example.org"

    user_query = mock.MagicMock()
    user_query.filter_by.return_value.one_or_none.return_value = user

    with (
        mock.patch.object(
            Compute4PUNCHJobManager,
            "workflow",
            new_callable=mock.PropertyMock,
            return_value=workflow,
        ),
        mock.patch.object(
            compute4punch_job_manager.Session,
            "query",
            return_value=user_query,
        ),
    ):
        manager.c4p_notification = "Complete"
        manager._create_c4p_job_description(job_inputs=[])

    command = manager.c4p_connection.exec_command.call_args.args[0]
    assert "notification = Complete" in command
    assert "notify_user = alice.hertzog@example.org" in command
