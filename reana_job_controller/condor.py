# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""HTCondor wrapper. Utilize libfactory's htcondorlib for job submission"""

import re
import json
import logging
import os
import sys
import time
import threading
import traceback
import htcondor
import classad
from subprocess import check_output
from retrying import retry

from flask import current_app as app
from reana_db.database import Session
from reana_db.models import Job

from reana_job_controller.errors import ComputingBackendSubmissionError
from reana_job_controller.htcondor_job_manager import HTCondorJobManager
from reana_job_controller.htcondor_job_manager import get_schedd

condorJobStatus = {
    'Unexpanded': 0,
    'Idle': 1,
    'Running': 2,
    'Removed': 3,
    'Completed': 4,
    'Held': 5,
    'Submission_Error': 6
}

def condor_watch_jobs(job_db):
    """Watch currently running HTCondor jobs.
    :param job_db: Dictionary which contains all current jobs.
    """
    schedd = get_schedd()
    ads = ['ClusterId', 'JobStatus', 'ExitCode']
    while True:
        logging.debug('Starting a new stream request to watch Condor Jobs')

        for job_id, job_dict in job_db.items():
            if job_db[job_id]['deleted']:
                continue
            condor_it = schedd.history('ClusterId == {0}'.format(
                job_dict['backend_job_id']), ads, match=1)
            try:
                condor_job = next(condor_it)
            except:
                # Did not match to any job in the history queue yet
                continue
            if condor_job['JobStatus'] == condorJobStatus['Completed']:
                if condor_job['ExitCode'] == 0:
                    job_db[job_id]['status'] = 'succeeded'
                else:
                    logging.info(
                        'Job job_id: {0}, condor_job_id: {1} failed'.format(
                            job_id, condor_job['ClusterId']))
                    job_db[job_id]['status'] = 'failed'
                # @todo: Grab/Save logs when job either succeeds or fails.
                job_db[job_id]['deleted'] = True
            elif condor_job['JobStatus'] == condorJobStatus['Held']:
                logging.info('Job Was held, will delette and set as failed')
                CondorJobManager.condor_delete_job(condor_job['ClusterId'])
                job_db[job_id]['deleted'] == True
             
        time.sleep(120)

def condor_delete_job(job, asynchronous=True):
    """Delete HTCondor job.

    :param job: The :string: HTCondor cluster ID of the job to be removed.
    :param asynchronous: Place holder for comparison to k8s.
    """

    schedd = get_schedd()
    schedd.act(htcondor.JobAction.Remove, 'ClusterID==%d' % job)

def start_watch_jobs_thread(JOB_DB):
    """Watch changes on jobs within HTCondor."""

    job_event_reader_thread = threading.Thread(target=condor_watch_jobs,
                                               args=(JOB_DB,))
    job_event_reader_thread.daemon = True
    job_event_reader_thread.start()


