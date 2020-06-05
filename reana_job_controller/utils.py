# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017-2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job controller utils."""

import logging
import os
import subprocess
import sys

import paramiko
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


@singleton
class SSHClient:
    """SSH Client."""

    def __init__(self, hostname=None, port=None):
        """Initialize ssh client."""
        self.hostname = hostname
        self.port = port
        self.establish_connection()

    def establish_connection(self):
        """Establish the connection."""
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh_client.connect(hostname=self.hostname, port=self.port, gss_auth=True)

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
