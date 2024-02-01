# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job controller utils."""

import csv
import logging
import os
import socket
import subprocess
import sys

from io import StringIO
from typing import List, Tuple

from reana_db.database import Session
from reana_db.models import Workflow


def singleton(cls):
    """Singelton decorator."""
    instances = {}

    def getinstance(**kwargs):
        if cls not in instances:
            instances[cls] = cls(**kwargs)
        return instances[cls]

    return getinstance


def update_workflow_logs(workflow_uuid, log_message):
    """Update workflow logs."""
    try:
        logging.info("Storing workflow logs: {}".format(workflow_uuid))
        workflow = Session.query(Workflow).filter_by(id_=workflow_uuid).one_or_none()
        workflow.logs += "\n" + log_message
        Session.commit()
    except Exception as e:
        logging.error("Exception while saving logs: {}".format(str(e)), exc_info=True)


def initialize_krb5_token(workflow_uuid):
    """Create kerberos ticket from mounted keytab_file."""
    cern_user = os.environ.get("CERN_USER")
    keytab_file = os.environ.get("CERN_KEYTAB")
    cmd = "kinit -kt /etc/reana/secrets/{} {}@CERN.CH".format(keytab_file, cern_user)

    if cern_user:
        try:
            subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError as err:
            msg = "Executing: {} \n Authentication failed: {}".format(cmd, err)
            Workflow.update_workflow_status(
                db_session=Session,
                workflow_uuid=workflow_uuid,
                status=None,
                new_logs=msg,
            )
            logging.error(msg, exc_info=True)
            sys.exit(1)
    else:
        msg = "CERN_USER is not set."
        logging.error(msg, exc_info=True)
        Workflow.update_workflow_status(
            db_session=Session, workflow_uuid=workflow_uuid, status=None, new_logs=msg
        )
        logging.error(msg, exc_info=True)


def csv_parser(
    input_csv: str,
    fieldnames: [List, Tuple],
    delimiter: str = "\t",
    replacements: dict = None,
    skip_initial_space: bool = False,
    skip_trailing_space: bool = False,
):
    """
    Parse CSV formatted input.

    :param input_csv: CSV formatted input
    :type input_csv: str
    :param fieldnames: corresponding field names
    :type fieldnames: [List, Tuple]
    :param delimiter: delimiter between entries
    :type delimiter: str
    :param replacements: fields to be replaced
    :type replacements: dict
    :param skip_initial_space: ignore whitespace immediately following the delimiter
    :type skip_initial_space: bool
    :param skip_trailing_space: ignore whitespace at the end of each csv row
    :type skip_trailing_space: bool
    """
    if skip_trailing_space:
        input_csv = "\n".join((line.strip() for line in input_csv.splitlines()))

    replacements = replacements or {}
    with StringIO(input_csv) as csv_input:
        csv_reader = csv.DictReader(
            csv_input,
            fieldnames=fieldnames,
            delimiter=delimiter,
            skipinitialspace=skip_initial_space,
        )
        for row in csv_reader:
            yield {
                key: value if value not in replacements.keys() else replacements[value]
                for key, value in row.items()
            }


def motley_cue_auth_strategy_factory(hostname):
    """
    Paramiko auth strategy factory that provides oauth based ssh token authentication.

    This auth strategy has been developed against the motley cue implementation of
    oauth based ssh token authentication on the server side.

    :param hostname: hostname of the ssh node
    :type hostname: str
    """
    # Using a factory to avoid a general dependency on libmytoken, paramiko and pyjwt
    from libmytoken import get_access_token_from_jwt_mytoken
    from paramiko.auth_strategy import AuthSource
    from time import time
    import jwt
    import requests

    class MotleyCueTokenAuth(AuthSource):
        def __init__(self):
            self._access_token = None
            self._access_token_expires_on = 0
            self.hostname = hostname
            self.username = self._get_deployed_username()
            super().__init__(username=self.username)

        @property
        def access_token(self):
            if not (self._access_token and self._is_access_token_valid()):
                self._refresh_access_token()
            return self._access_token

        def authenticate(self, transport):
            return transport.auth_interactive(
                username=self.username, handler=self.motley_cue_auth_handler
            )

        def _is_access_token_valid(self):
            return (
                self._access_token_expires_on - time() > 100
            )  # token should be at least valid for 100 s

        def _get_access_token_expiry_date(self):
            decoded_token = jwt.decode(
                self._access_token,
                options={"verify_signature": False, "verify_aud": False},
            )
            return decoded_token["exp"]

        def _get_deployed_username(self):
            headers = {"Authorization": f"Bearer {self.access_token}"}
            req = requests.get(
                f"https://{self.hostname}/user/deploy", headers=headers, verify=True
            )
            req.raise_for_status()
            return req.json()["credentials"]["ssh_user"]

        def motley_cue_auth_handler(self, title, instructions, prompt_list):
            return [
                self.access_token if (echo and "Access Token" in prompt) else ""
                for prompt, echo in prompt_list
            ]

        def _refresh_access_token(self):
            self._access_token = get_access_token_from_jwt_mytoken(
                os.environ.get("HELMHOLTZ_TOP")
            )
            self._access_token_expires_on = self._get_access_token_expiry_date()

    return MotleyCueTokenAuth()


@singleton
class SSHClient:
    """SSH Client."""

    import paramiko

    def __init__(
        self,
        hostname=None,
        port=None,
        timeout=None,
        banner_timeout=None,
        auth_timeout=None,
        auth_strategy=None,
    ):
        """Initialize ssh client."""
        if hostname:
            # resolve IPv4 address of DNS load-balanced Slurm nodes to ease connection troubles
            try:
                self.hostname = socket.gethostbyname_ex(hostname)[2][0]
            except Exception:
                self.hostname = hostname
        else:
            self.hostname = hostname
        self.port = port
        self.timeout = timeout
        self.banner_timeout = banner_timeout
        self.auth_timeout = auth_timeout
        self.auth_strategy = auth_strategy
        self.ssh_client = self.paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(self.paramiko.AutoAddPolicy())
        self.establish_connection()

    def establish_connection(self):
        """Establish the connection."""
        # self.paramiko.util.log_to_file('/tmp/paramiko.log')
        self.ssh_client.connect(
            hostname=self.hostname,
            allow_agent=False,
            auth_timeout=self.auth_timeout,
            banner_timeout=self.banner_timeout,
            gss_auth=True,
            gss_host=self.hostname,
            gss_trust_dns=True,
            look_for_keys=False,
            port=self.port,
            timeout=self.timeout,
            auth_strategy=self.auth_strategy,
        )

    def exec_command(self, command):
        """Execute command and return exit code."""
        if not self.ssh_client.get_transport().active:
            self.establish_connection()
        try:
            stdin, stdout, stderr = self.ssh_client.exec_command(command)
            if stdout.channel.recv_exit_status() != 0:
                raise Exception(stderr.read().decode("utf-8"))
            return stdout.read().decode("utf-8")
        except Exception as e:
            logging.error(
                "Exception while executing cmd: {} \n{}".format(command, str(e)),
                exc_info=True,
            )
