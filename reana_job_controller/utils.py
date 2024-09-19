# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2022, 2023, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job controller utils."""

import logging
import os
import socket
import subprocess
import sys
from logging import Formatter, LogRecord

from reana_db.database import Session
from reana_db.models import Workflow


class MultilineFormatter(Formatter):
    """Logging formatter for multiline logs."""

    def format(self, record: LogRecord):
        """Format multiline log message.

        :param record: LogRecord object.
        :type record: logging.LogRecord

        :return: Formatted log message.
        :rtype: str
        """
        save_msg = str(record.msg)
        output = ""
        lines = save_msg.splitlines()
        for line in lines:
            record.msg = line
            output += super().format(record) + "\n"
        output = output.strip()
        record.msg = save_msg
        record.message = output

        return output


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
