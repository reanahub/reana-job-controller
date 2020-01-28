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

from reana_job_controller.htcondorcern_job_manager import \
    HTCondorJobManagerCERN
from reana_job_controller.job_db import JOB_DB
from reana_job_controller.kubernetes_job_manager import KubernetesJobManager
from reana_job_controller.htcondorvc3_job_manager import \
    HTCondorJobManagerVC3
from reana_job_controller.slurmcern_job_manager import SlurmJobManagerCERN
from reana_job_controller.utils import SSHClient, singleton


class JobMonitor():
    """Job monitor interface."""

    def __init__(self, thread_name, app=None):
        """Initialize REANA job monitors."""
        self.job_event_reader_thread = threading.Thread(
            name=thread_name,
            target=self.watch_jobs,
            args=(JOB_DB, app))
        self.job_event_reader_thread.daemon = True
        self.job_event_reader_thread.start()

    def watch_jobs(self, job_db, app):
        """Monitor running jobs."""
        raise NotImplementedError


@singleton
class JobMonitorKubernetes(JobMonitor):
    """Kubernetes job monitor."""

    def __init__(self, app=None):
        """Initialize Kubernetes job monitor thread."""
        super(__class__, self).__init__(
            thread_name='kubernetes_job_monitor'
        )

    def get_container_logs(self, last_spawned_pod):
        """Get job pod's containers' logs."""
        try:
            pod_logs = ''
            pod = current_k8s_corev1_api_client.read_namespaced_pod(
                namespace=last_spawned_pod.metadata.namespace,
                name=last_spawned_pod.metadata.name)
            containers = pod.spec.init_containers + pod.spec.containers \
                if pod.spec.init_containers else pod.spec.containers
            for container in containers:
                container_log = \
                    current_k8s_corev1_api_client.read_namespaced_pod_log(
                        namespace=last_spawned_pod.metadata.namespace,
                        name=last_spawned_pod.metadata.name,
                        container=container.name)
                pod_logs += '{}: \n {} \n'.format(
                    container.name, container_log)
            return pod_logs
        except client.rest.ApiException as e:
            logging.error(
                "Error while connecting to Kubernetes API: {}".format(e))
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.error("Unexpected error: {}".format(e))

    def watch_jobs(self, job_db, app=None):
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
                        self.get_container_logs(last_spawned_pod)
                    store_logs(job_id=job_id, logs=job_db[job_id]['log'])

                    logging.info('Cleaning Kubernetes job {} ...'.format(
                        kubernetes_job_id))
                    KubernetesJobManager.stop(kubernetes_job_id)
                    job_db[job_id]['deleted'] = True
            except client.rest.ApiException as e:
                logging.error(
                    "Error while connecting to Kubernetes API: {}".format(e))
            except Exception as e:
                logging.error(traceback.format_exc())
                logging.error("Unexpected error: {}".format(e))


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
class JobMonitorHTCondorCERN(JobMonitor):
    """HTCondor jobs monitor CERN."""

    def __init__(self, app):
        """Initialize HTCondor job monitor thread."""
        super(__class__, self).__init__(
            thread_name='htcondor_job_monitor',
            app=app
        )

    def format_condor_job_que_query(self, backend_job_ids):
        """Format HTCondor job que query."""
        base_query = 'ClusterId == {} ||'
        query = ''
        for job_id in backend_job_ids:
            query += base_query.format(job_id)
        return query[:-2]

    def watch_jobs(self, job_db, app):
        """Watch currently running HTCondor jobs.

        :param job_db: Dictionary which contains all current jobs.
        """
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
                future_condor_jobs = app.htcondor_executor.submit(
                    query_condor_jobs,
                    app,
                    backend_job_ids)
                condor_jobs = future_condor_jobs.result()
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
                        future_job_history = app.htcondor_executor.submit(
                            HTCondorJobManagerCERN.find_job_in_history,
                            job_dict['backend_job_id'])
                        condor_job = future_job_history.result()
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
                            app.htcondor_executor.submit(
                                HTCondorJobManagerCERN.spool_output,
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

@singleton
class JobMonitorHTCondorVC3():
    """HTCondor jobs monitor VC3."""

    def __init__(self):
        """Initialize HTCondor job monitor thread."""
        from reana_job_controller.htcondorvc3_job_manager import get_schedd
        self.schedd = get_schedd()
        self.job_event_reader_thread = threading.Thread(
            name='htcondorvc3_job_monitor',
            target=self.watch_jobs,
            args=(JOB_DB,))
        self.job_event_reader_thread.daemon = True
        self.job_event_reader_thread.start()

    def watch_jobs(self, job_db):
        """Watch currently running HTCondor jobs.

        :param job_db: Dictionary which contains all current jobs.
        """
        #schedd = get_schedd()
        schedd = self.schedd
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
                    HTCondorJobManagerVC3.condor_delete_job(condor_job['ClusterId'])
                    job_db[job_id]['deleted'] == True
                 
            time.sleep(120)


slurmJobStatus = {
    'failed': ['BOOT_FAIL', 'CANCELLED', 'DEADLINE', 'FAILED', 'NODE_FAIL',
               'OUT_OF_MEMORY', 'PREEMPTED', 'TIMEOUT', 'SUSPENDED',
               'STOPPED'],
    'succeeded': ['COMPLETED'],
    'running': ['CONFIGURING', 'COMPLETING', 'RUNNING', 'STAGE_OUT'],
    'idle': ['PENDING', 'REQUEUE_FED', 'REQUEUE_HOLD', 'RESV_DEL_HOLD',
             'REQUEUED', 'RESIZING']
    # 'REVOKED',
    # 'SIGNALING',
    # 'SPECIAL_EXIT',
}


@singleton
class JobMonitorSlurmCERN(JobMonitor):
    """Slurm jobs monitor CERN."""

    def __init__(self, app=None):
        """Initialize Slurm job monitor thread."""
        super(__class__, self).__init__(
            thread_name='slurm_job_monitor'
        )

    def format_slurm_job_query(self, backend_job_ids):
        """Format Slurm job query."""
        cmd = 'sacct --jobs {} --noheader --allocations --parsable ' \
              '--format State,JobID'.format(','.join(backend_job_ids))
        return cmd

    def watch_jobs(self, job_db, app=None):
        """Use SSH connection to slurm submitnode to monitor jobs.

        :param job_db: Dictionary which contains all running jobs.
        """
        slurm_connection = SSHClient(
            hostname=SlurmJobManagerCERN.SLURM_HEADNODE_HOSTNAME,
            port=SlurmJobManagerCERN.SLURM_HEADNODE_PORT,
        )
        statuses_to_skip = ['succeeded', 'failed']
        while True:
            logging.debug('Starting a new stream request to watch Jobs')
            try:
                slurm_jobs = {}
                for id, job_dict in job_db.items():
                    if (not job_db[id]['deleted'] and
                       job_db[id]['compute_backend'] == 'slurmcern' and
                       not job_db[id]['status'] in statuses_to_skip):
                        slurm_jobs[job_dict['backend_job_id']] = id
                if not slurm_jobs.keys():
                    logging.error('No slurm jobs')
                    continue
                slurm_query_cmd = self.format_slurm_job_query(
                    slurm_jobs.keys())
                stdout = slurm_connection.exec_command(slurm_query_cmd)
                for item in stdout.rstrip().split('\n'):
                    slurm_job_status = item.split('|')[0]
                    slurm_job_id = item.split('|')[1]
                    job_id = slurm_jobs[slurm_job_id]
                    if slurm_job_status in slurmJobStatus['succeeded']:
                        SlurmJobManagerCERN.get_outputs()
                        job_db[job_id]['status'] = 'succeeded'
                        job_db[job_id]['deleted'] = True
                    if slurm_job_status in slurmJobStatus['failed']:
                        job_db[job_id]['status'] = 'failed'
                        job_db[job_id]['deleted'] = True
                    if slurm_job_status in slurmJobStatus['failed'] or \
                       slurm_job_status in slurmJobStatus['succeeded']:
                        job_db[job_id]['log'] = \
                            SlurmJobManagerCERN.get_logs(
                                backend_job_id=job_dict['backend_job_id'],
                                workspace=job_db[
                                    job_id]['obj'].workflow_workspace)
                        store_logs(logs=job_db[job_id]['log'], job_id=job_id)
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


def query_condor_jobs(app, backend_job_ids):
    """Query condor jobs."""
    ads = ['ClusterId', 'JobStatus', 'ExitCode', 'ExitStatus',
           'HoldReasonCode']
    query = format_condor_job_que_query(backend_job_ids)
    schedd = HTCondorJobManagerCERN._get_schedd()
    logging.info('Querying jobs {}'.format(backend_job_ids))
    condor_jobs = schedd.xquery(requirements=query, projection=ads)
    return condor_jobs
