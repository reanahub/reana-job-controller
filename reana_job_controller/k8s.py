# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Kubernetes wrapper."""

import logging
import threading
import traceback

from flask import current_app as app
from kubernetes import client, watch
from kubernetes.client.models.v1_delete_options import V1DeleteOptions
from kubernetes.client.rest import ApiException
from reana_commons.k8s.api_client import (current_k8s_batchv1_api_client,
                                          current_k8s_corev1_api_client)
from reana_db.database import Session
from reana_db.models import Job

from reana_job_controller import config
from reana_job_controller.kubernetes_job_manager import KubernetesJobManager


def k8s_watch_jobs(job_db):
    """Open stream connection to k8s apiserver to watch all jobs status.

    :param job_db: Dictionary which contains all current jobs.
    :param config: configuration to connect to k8s apiserver.
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

                # Taking note of the remaining jobs since deletion might not
                # happen straight away.
                remaining_jobs = dict()
                for job_id, job_dict in job_db.items():
                    if not job_db[job_id]['deleted']:
                        remaining_jobs[job_dict['backend_job_id']] = job_id
                if (not job_db.get(remaining_jobs.get(job.metadata.name)) or
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
                elif (job.status.failed and
                      job.status.failed >= config.MAX_JOB_RESTARTS):
                    logging.info(
                        'Job job_id: {}, kubernetes_job_id: {} failed.'.format(
                            job_id,
                            kubernetes_job_id)
                    )
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
                # Store job logs
                try:
                    logging.info('Storing job logs: {}'.
                                 format(job_db[job_id]['log']))
                    Session.query(Job).filter_by(id_=job_id). \
                        update(dict(logs=job_db[job_id]['log']))
                    Session.commit()

                except Exception as e:
                    logging.debug('Could not retrieve'
                                  ' logs for object: {}'.
                                  format(last_spawned_pod))
                    logging.debug('Exception: {}'.format(str(e)))

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


def start_watch_jobs_thread(JOB_DB):
    """Watch changes on job objects on kubernetes."""
    job_event_reader_thread = threading.Thread(target=k8s_watch_jobs,
                                               args=(JOB_DB,))
    job_event_reader_thread.daemon = True
    job_event_reader_thread.start()
