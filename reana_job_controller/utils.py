# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017-2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job controller utils."""

import logging

import paramiko
from reana_db.database import Session
from reana_db.models import Workflow


def singleton(cls):
    """Singelton decorator."""
    instances = {}

    def getinstance():
        if cls not in instances:
            instances[cls] = cls()
        return instances[cls]
    return getinstance


def update_workflow_logs(workflow_uuid, log_message):
    """Update workflow logs."""
    try:
        logging.info('Storing workflow logs: {}'.format(workflow_uuid))
        workflow = Session.query(Workflow).filter_by(id_=workflow_uuid).\
            one_or_none()
        workflow.logs += '\n' + log_message
        Session.commit()
    except Exception as e:
        logging.error('Exception while saving logs: {}'.format(str(e)),
                      exc_info=True)


@singleton
class SSHClient():
    """SSH Client."""

    def __init__(self, hostname, username, password, port):
        """Initialize ssh client."""
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy())
        self.ssh_client.connect(
            hostname,
            username,
            password,
            port)
