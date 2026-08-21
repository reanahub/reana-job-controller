# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2024, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

import logging
from unittest import mock

import pytest

import reana_job_controller.utils as utils
from reana_commons.k8s.secrets import Secret, UserSecrets
from reana_job_controller.config import SLURM_PARTITION
from reana_job_controller.utils import (
    MultilineFormatter,
    initialize_krb5_token,
)

"""REANA-Job-Controller utils tests."""


@pytest.mark.parametrize(
    "message,expected_output",
    [
        (
            "test",
            "name | INFO | test",
        ),
        (
            "test\n",
            "name | INFO | test",
        ),
        (
            "test\ntest",
            "name | INFO | test\nname | INFO | test",
        ),
        (
            "test\ntest\n\n\n",
            "name | INFO | test\nname | INFO | test\nname | INFO | \nname | INFO |",
        ),
        (
            "   test\ntest   ",
            "name | INFO |    test\nname | INFO | test",
        ),
        (
            "   t e s\tt\n     t e s t   ",
            "name | INFO |    t e s\tt\nname | INFO |      t e s t",
        ),
    ],
)
def test_multiline_formatter_format(message, expected_output):
    """Test MultilineFormatter formatting."""
    formatter = MultilineFormatter("%(name)s | " "%(levelname)s | %(message)s")
    assert (
        formatter.format(
            logging.LogRecord(
                "name",
                logging.INFO,
                "pathname",
                1,
                message,
                None,
                None,
            ),
        )
        == expected_output
    )


def test_ssh_client_uses_resolved_ipv4_for_connection_and_hostname_for_gss():
    """Test SSHClient keeps hostname as Kerberos target when PTR is unavailable."""
    ssh_client = mock.MagicMock()
    paramiko_mock = mock.MagicMock()
    paramiko_mock.SSHClient.return_value = ssh_client

    with (
        mock.patch.object(
            utils.SSHClient.__closure__[0].cell_contents, "paramiko", paramiko_mock
        ),
        mock.patch.object(
            utils.socket,
            "gethostbyname_ex",
            return_value=("slurm.example.org", [], ["10.0.0.10"]),
        ),
        mock.patch.object(utils.socket, "getfqdn", return_value="10.0.0.10"),
    ):
        utils.SSHClient.__closure__[1].cell_contents.clear()
        try:
            utils.SSHClient(hostname="slurm.example.org", port=22)
        finally:
            utils.SSHClient.__closure__[1].cell_contents.clear()

    ssh_client.connect.assert_called_once_with(
        hostname="10.0.0.10",
        allow_agent=False,
        auth_timeout=None,
        banner_timeout=None,
        gss_auth=True,
        gss_host="slurm.example.org",
        gss_trust_dns=False,
        look_for_keys=False,
        port=22,
        timeout=None,
        auth_strategy=None,
    )


def test_ssh_client_uses_reverse_dns_name_for_gss_when_available():
    """Test SSHClient uses selected IPv4 PTR name as Kerberos target."""
    ssh_client = mock.MagicMock()
    paramiko_mock = mock.MagicMock()
    paramiko_mock.SSHClient.return_value = ssh_client

    with (
        mock.patch.object(
            utils.SSHClient.__closure__[0].cell_contents, "paramiko", paramiko_mock
        ),
        mock.patch.object(
            utils.socket,
            "gethostbyname_ex",
            return_value=("slurm.example.org", [], ["10.0.0.11"]),
        ),
        mock.patch.object(
            utils.socket, "getfqdn", return_value="slurmgate01.example.org"
        ),
    ):
        utils.SSHClient.__closure__[1].cell_contents.clear()
        try:
            utils.SSHClient(hostname="slurm.example.org", port=22)
        finally:
            utils.SSHClient.__closure__[1].cell_contents.clear()

    ssh_client.connect.assert_called_once_with(
        hostname="10.0.0.11",
        allow_agent=False,
        auth_timeout=None,
        banner_timeout=None,
        gss_auth=True,
        gss_host="slurmgate01.example.org",
        gss_trust_dns=False,
        look_for_keys=False,
        port=22,
        timeout=None,
        auth_strategy=None,
    )


def test_ssh_client_prefers_explicit_gss_host():
    """Test SSHClient supports overriding the Kerberos target."""
    ssh_client = mock.MagicMock()
    paramiko_mock = mock.MagicMock()
    paramiko_mock.SSHClient.return_value = ssh_client

    with (
        mock.patch.object(
            utils.SSHClient.__closure__[0].cell_contents, "paramiko", paramiko_mock
        ),
        mock.patch.object(
            utils.socket,
            "gethostbyname_ex",
            return_value=("slurm.example.org", [], ["10.0.0.11"]),
        ),
        mock.patch.object(utils.socket, "getfqdn") as getfqdn,
    ):
        utils.SSHClient.__closure__[1].cell_contents.clear()
        try:
            utils.SSHClient(
                hostname="slurm.example.org",
                gss_host="slurmgate04.example.org",
                port=22,
            )
        finally:
            utils.SSHClient.__closure__[1].cell_contents.clear()

    getfqdn.assert_not_called()
    ssh_client.connect.assert_called_once_with(
        hostname="10.0.0.11",
        allow_agent=False,
        auth_timeout=None,
        banner_timeout=None,
        gss_auth=True,
        gss_host="slurmgate04.example.org",
        gss_trust_dns=False,
        look_for_keys=False,
        port=22,
        timeout=None,
        auth_strategy=None,
    )


def test_ssh_client_exec_command_raises_remote_errors():
    """Test SSHClient propagates command execution failures."""
    ssh_client = mock.MagicMock()
    ssh_client.get_transport.return_value.active = True
    stdout = mock.MagicMock()
    stdout.channel.recv_exit_status.return_value = 1
    stderr = mock.MagicMock()
    stderr.read.return_value = b"remote command failed"
    ssh_client.exec_command.return_value = (mock.MagicMock(), stdout, stderr)
    paramiko_mock = mock.MagicMock()
    paramiko_mock.SSHClient.return_value = ssh_client

    with mock.patch.object(
        utils.SSHClient.__closure__[0].cell_contents, "paramiko", paramiko_mock
    ):
        utils.SSHClient.__closure__[1].cell_contents.clear()
        try:
            client = utils.SSHClient(hostname="slurm.example.org", port=22)
            with pytest.raises(Exception, match="remote command failed"):
                client.exec_command("failing command")
        finally:
            utils.SSHClient.__closure__[1].cell_contents.clear()


def test_slurm_partition_uses_current_cern_default():
    """Test default Slurm partition follows the current CERN cluster."""
    assert SLURM_PARTITION == "photon"


def test_initialize_krb5_token_uses_scoped_secrets(monkeypatch):
    """Kerberos auth should read credentials from the scoped secret set."""
    scoped_secrets = UserSecrets(
        user_id="123",
        k8s_secret_name="k8s-secret",
        secrets=[
            Secret("CERN_USER", "env", "johndoe"),
            Secret("CERN_KEYTAB", "env", ".keytab"),
        ],
    )
    monkeypatch.delenv("CERN_USER", raising=False)
    monkeypatch.delenv("CERN_KEYTAB", raising=False)

    with mock.patch("reana_job_controller.utils.subprocess.check_output") as mocked:
        initialize_krb5_token("workflow-uuid", secrets=scoped_secrets)

    mocked.assert_called_once_with(
        "kinit -kt /etc/reana/secrets/.keytab johndoe@CERN.CH",
        shell=True,
    )
