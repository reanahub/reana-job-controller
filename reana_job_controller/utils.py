# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017-2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job controller utils."""

import logging

from reana_db.database import Session
from reana_db.models import Workflow


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
