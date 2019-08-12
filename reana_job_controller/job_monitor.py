# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job monitoring wrapper."""

import logging
import threading
import time
import traceback

from kubernetes import client, watch
from reana_commons.k8s.api_client import (current_k8s_batchv1_api_client,
                                          current_k8s_corev1_api_client)
from reana_db.database import Session
from reana_db.models import Job

from reana_job_controller import config
from reana_job_controller.htcondorcern_job_manager import \
    HTCondorJobManagerCERN
from reana_job_controller.job_db import JOB_DB
from reana_job_controller.kubernetes_job_manager import KubernetesJobManager
from reana_job_controller.utils import singleton


@singleton
class JobMonitorKubernetes():
    """Kubernetes job monitor."""

    def __init__(self):
        """Initialize Kubernetes job monitor thread."""
        self.job_event_reader_thread = threading.Thread(
            name='kubernetes_job_monitor',
            target=self.watch_jobs,
            args=(JOB_DB,))
        self.job_event_reader_thread.daemon = True
        self.job_event_reader_thread.start()

    def watch_jobs(self, job_db):
        """Open stream connection to k8s apiserver to watch all jobs status.

        :param job_db: Dictionary which contains all current jobs.
        """
        while True:
            logging.debug('Starting a new stream request to watch Jobs')
            try:
                w = watch.Watch()
                for event in w.stream(
                    current_k8s_batchv1_api_client.list_job_for_all_namespaces
                ):
                    logging.info(
                        'New Job event received: {0}'.format(event['type']))
                    job = event['object']

                    # Taking note of the remaining jobs since deletion might
                    # not happen straight away.
                    remaining_jobs = dict()
                    for job_id, job_dict in job_db.items():
                        if not job_db[job_id]['deleted']:
                            remaining_jobs[job_dict['backend_job_id']] = job_id
                    if (not job_db.get(remaining_jobs.get(
                            job.metadata.name)) or
                            job.metadata.name not in remaining_jobs):
                        # Ignore jobs not created by this specific instance
                        # or already deleted jobs.
                        continue
                    job_id = remaining_jobs[job.metadata.name]
                    kubernetes_job_id = job.metadata.name
                    if job.status.succeeded:
                        logging.info(
                            'Job job_id: {}, kubernetes_job_id: {}'
                            ' succeeded.'.format(job_id, kubernetes_job_id)
                        )
                        job_db[job_id]['status'] = 'succeeded'
                    elif job.status.failed:
                        logging.info(
                            'Job job_id: {}, kubernetes_job_id: {} failed.'
                            .format(job_id, kubernetes_job_id))
                        job_db[job_id]['status'] = 'failed'
                    else:
                        continue
                    # Grab logs when job either succeeds or fails.
                    logging.info('Getting last spawned pod for kubernetes'
                                 ' job {}'.format(kubernetes_job_id))
                    last_spawned_pod = \
                        current_k8s_corev1_api_client.list_namespaced_pod(
                            namespace=job.metadata.namespace,
                            label_selector='job-name={job_name}'.format(
                                job_name=kubernetes_job_id)).items[-1]
                    logging.info('Grabbing pod {} logs...'.format(
                        last_spawned_pod.metadata.name))
                    job_db[job_id]['log'] = \
                        current_k8s_corev1_api_client.read_namespaced_pod_log(
                            namespace=last_spawned_pod.metadata.namespace,
                            name=last_spawned_pod.metadata.name)
                    store_logs(job_id=job_id, logs=job_db[job_id]['log'])

                    logging.info('Cleaning Kubernetes job {} ...'.format(
                        kubernetes_job_id))
                    KubernetesJobManager.stop(kubernetes_job_id)
                    job_db[job_id]['deleted'] = True
            except client.rest.ApiException as e:
                logging.debug(
                    "Error while connecting to Kubernetes API: {}".format(e))
            except Exception as e:
                logging.error(traceback.format_exc())
                logging.debug("Unexpected error: {}".format(e))


condorJobStatus = {
    'Unexpanded': 0,
    'Idle': 1,
    'Running': 2,
    'Removed': 3,
    'Completed': 4,
    'Held': 5,
    'Submission_Error': 6
}


@singleton
class JobMonitorHTCondorCERN():
    """HTCondor jobs monitor CERN."""

    def __init__(self):
        """Initialize HTCondor job monitor thread."""
        self.job_event_reader_thread = threading.Thread(
            name='htcondorcern_job_monitor',
            target=self.watch_jobs,
            args=(JOB_DB,))
        self.job_event_reader_thread.daemon = True
        self.job_event_reader_thread.start()

    def watch_jobs(self, job_db):
        """Watch currently running HTCondor jobs.

        :param job_db: Dictionary which contains all current jobs.
        """
        schedd = HTCondorJobManagerCERN._get_schedd()
        ads = \
            ['ClusterId', 'JobStatus', 'ExitCode', 'ExitStatus',
             'HoldReasonCode']
        ignore_hold_codes = [35, 16]
        statuses_to_skip = ['succeeded', 'failed']
        while True:
            try:
                logging.info(
                    'Starting a new stream request to watch Condor Jobs')
                backend_job_ids = \
                    [job_dict['backend_job_id'] for id, job_dict in
                     job_db.items()
                     if not job_db[id]['deleted'] and
                     job_db[id]['compute_backend'] == 'htcondorcern']
                query = format_condor_job_que_query(backend_job_ids)
                condor_jobs = schedd.xquery(
                    requirements=query,
                    projection=ads)
                for job_id, job_dict in job_db.items():
                    if job_db[job_id]['deleted'] or \
                       job_db[job_id]['compute_backend'] != 'htcondorcern' or \
                       job_db[job_id]['status'] in statuses_to_skip:
                        continue
                    try:
                        condor_job = \
                            next(job for job in condor_jobs
                                 if job['ClusterId'] == job_dict
                                 ['backend_job_id'])
                    except Exception:
                        msg = 'Job with id {} was not found in schedd.'\
                            .format(job_dict['backend_job_id'])
                        logging.error(msg)
                        condor_job = \
                            HTCondorJobManagerCERN.find_job_in_history(
                                job_dict['backend_job_id'])
                        if condor_job:
                            msg = 'Job was found in history. {}'.format(
                                str(condor_job))
                            logging.error(msg)
                            job_db[job_id]['status'] = 'failed'
                            job_db[job_id]['log'] = msg
                        continue
                    if condor_job['JobStatus'] == condorJobStatus['Completed']:
                        exit_code = condor_job.get(
                            'ExitCode',
                            condor_job.get('ExitStatus'))
                        if exit_code == 0:
                            HTCondorJobManagerCERN.spool_output(
                                job_dict['backend_job_id'])
                            job_db[job_id]['status'] = 'succeeded'
                        else:
                            logging.info(
                                'Job job_id: {0}, condor_job_id: {1} '
                                'failed'.format(job_id,
                                                condor_job['ClusterId']))
                            job_db[job_id]['status'] = 'failed'
                        job_db[job_id]['log'] = \
                            HTCondorJobManagerCERN.get_logs(
                                backend_job_id=job_dict['backend_job_id'],
                                workspace=job_db[
                                    job_id]['obj'].workflow_workspace)
                        store_logs(logs=job_db[job_id]['log'], job_id=job_id)
                        job_db[job_id]['deleted'] = True
                    elif (condor_job['JobStatus'] ==
                          condorJobStatus['Held'] and
                          int(condor_job['HoldReasonCode']) not in
                          ignore_hold_codes):
                        logging.info(
                            'Job was held, will delete and set as failed')
                        HTCondorJobManagerCERN.stop(
                            condor_job['ClusterId'])
                        job_db[job_id]['deleted'] = True
                time.sleep(120)
            except Exception as e:
                logging.error("Unexpected error: {}".format(e), exc_info=True)
                time.sleep(120)


def store_logs(logs, job_id):
    """Write logs to DB."""
    try:
        logging.info('Storing job logs: {}'.format(job_id))
        Session.query(Job).filter_by(id_=job_id).update(dict(logs=logs))
        Session.commit()
    except Exception as e:
        logging.error('Exception while saving logs: {}'.format(str(e)),
                      exc_info=True)


def format_condor_job_que_query(backend_job_ids):
    """Format HTCondor job que query."""
    base_query = 'ClusterId == {} ||'
    query = ''
    for job_id in backend_job_ids:
        query += base_query.format(job_id)
    return query[:-2]
