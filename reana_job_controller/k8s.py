# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Kubernetes wrapper."""

import ast
import logging
import os
import threading
import traceback

from flask import current_app as app
from kubernetes import client, watch
from kubernetes.client.models.v1_delete_options import V1DeleteOptions
from kubernetes.client.rest import ApiException
from reana_commons.config import CVMFS_REPOSITORIES
from reana_commons.k8s.api_client import (current_k8s_batchv1_api_client,
                                          current_k8s_corev1_api_client)
from reana_commons.k8s.volumes import get_shared_volume, get_k8s_cvmfs_volume
from reana_db.database import Session
from reana_db.models import Job

from reana_job_controller import config
from reana_job_controller.config import SHARED_VOLUME_PATH_ROOT
from reana_job_controller.errors import ComputingBackendSubmissionError


def add_shared_volume(job, workflow_workspace):
    """Add shared CephFS volume to a given job spec.

    :param job: Kubernetes job spec.
    :param workflow_workspace: Absolute path to the job's workflow workspace.
    """
    volume_mount, volume = get_shared_volume(workflow_workspace,
                                             SHARED_VOLUME_PATH_ROOT)
    job['spec']['template']['spec']['containers'][0]['volumeMounts'].append(
        volume_mount
    )
    job['spec']['template']['spec']['volumes'].append(volume)


def k8s_instantiate_job(job_id, workflow_workspace, docker_img, cmd,
                        cvmfs_mounts, env_vars, shared_file_system, job_type,
                        namespace='default'):
    """Create Kubernetes job.

    :param job_id: Job uuid.
    :param workflow_workspace: Absolute path to the job's workflow workspace.
    :param docker_img: Docker image to run the job.
    :param cmd: Command provided to the docker container.
    :param cvmfs_mounts: List of CVMFS volumes to mount in job pod.
    :param env_vars: Dictionary representing environment variables
        as {'var_name': 'var_value'}.
    :param namespace: Job's namespace.
    :shared_file_system: Boolean which represents whether the job
        should have a shared file system mounted.
    :returns: A :class:`kubernetes.client.models.v1_job.V1Job` corresponding
        to the created job, None if the creation could not take place.
    """
    job = {
        'kind': 'Job',
        'apiVersion': 'batch/v1',
        'metadata': {
            'name': job_id,
            'namespace': namespace
        },
        'spec': {
            'backoffLimit': app.config['MAX_JOB_RESTARTS'],
            'autoSelector': True,
            'template': {
                'metadata': {
                    'name': job_id
                },
                'spec': {
                    'containers': [
                        {
                            'name': job_id,
                            'image': docker_img,
                            'env': [],
                            'volumeMounts': []
                        },
                    ],
                    'volumes': [],
                    'restartPolicy': 'Never'
                }
            }
        }
    }

    if cmd:
        import shlex
        (job['spec']['template']['spec']['containers']
         [0]['command']) = shlex.split(cmd)

    if env_vars:
        for var, value in env_vars.items():
            job['spec']['template']['spec']['containers'][0]['env'].append(
                {'name': var, 'value': value}
            )

    if shared_file_system:
        add_shared_volume(job, workflow_workspace)

    if cvmfs_mounts != 'false':
        cvmfs_map = {}
        for cvmfs_mount_path in ast.literal_eval(cvmfs_mounts):
            if cvmfs_mount_path in CVMFS_REPOSITORIES:
                cvmfs_map[
                    CVMFS_REPOSITORIES[cvmfs_mount_path]] = cvmfs_mount_path

        for repository, mount_path in cvmfs_map.items():
            volume = get_k8s_cvmfs_volume(repository)

            (job['spec']['template']['spec']['containers'][0]
                ['volumeMounts'].append(
                    {'name': volume['name'],
                     'mountPath': '/cvmfs/{}'.format(mount_path)}
            ))
            job['spec']['template']['spec']['volumes'].append(volume)

    # add better handling
    try:
        api_response = \
            current_k8s_batchv1_api_client.create_namespaced_job(
                namespace=namespace, body=job)
        return api_response
    except client.rest.ApiException as e:
        logging.debug("Error while connecting to Kubernetes API: {}".format(e))
    except Exception as e:
        logging.error(traceback.format_exc())
        logging.debug("Unexpected error: {}".format(e))


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
                # happend straight away.
                remaining_jobs = [j for j in job_db.keys()
                                  if not job_db[j]['deleted']]
                if (not job_db.get(job.metadata.name) or
                        job.metadata.name not in remaining_jobs):
                    # Ignore jobs not created by this specific instance
                    # or already deleted jobs.
                    continue
                elif job.status.succeeded:
                    logging.info(
                        'Job {} succeeded.'.format(
                            job.metadata.name)
                    )
                    job_db[job.metadata.name]['status'] = 'succeeded'
                elif (job.status.failed and
                      job.status.failed >= config.MAX_JOB_RESTARTS):
                    logging.info('Job {} failed.'.format(
                        job.metadata.name))
                    job_db[job.metadata.name]['status'] = 'failed'
                else:
                    continue
                # Grab logs when job either succeeds or fails.
                logging.info('Getting last spawned pod for job {}'.format(
                    job.metadata.name))
                last_spawned_pod = \
                    current_k8s_corev1_api_client.list_namespaced_pod(
                        job.metadata.namespace,
                        label_selector='job-name={job_name}'.format(
                            job_name=job.metadata.name)).items[-1]
                logging.info('Grabbing pod {} logs...'.format(
                    last_spawned_pod.metadata.name))
                job_db[job.metadata.name]['log'] = \
                    current_k8s_corev1_api_client.read_namespaced_pod_log(
                        namespace=last_spawned_pod.metadata.namespace,
                        name=last_spawned_pod.metadata.name)
                # Store job logs
                try:
                    logging.info('Storing job logs: {}'.
                                 format(job_db[job.metadata.name]['log']))
                    Session.query(Job).filter_by(id_=job.metadata.name). \
                        update(dict(logs=job_db[job.metadata.name]['log']))
                    Session.commit()

                except Exception as e:
                    logging.debug('Could not retrieve'
                                  ' logs for object: {}'.
                                  format(last_spawned_pod))
                    logging.debug('Exception: {}'.format(str(e)))

                logging.info('Cleaning job {} ...'.format(
                    job.metadata.name))
                k8s_delete_job(job)
                job_db[job.metadata.name]['deleted'] = True
        except client.rest.ApiException as e:
            logging.debug(
                "Error while connecting to Kubernetes API: {}".format(e))
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.debug("Unexpected error: {}".format(e))


def k8s_delete_job(job, asynchronous=True):
    """Delete Kubernetes job.

    :param job: The :class:`kubernetes.client.models.v1_job.V1Job` to be
        deleted.
    :param asynchronous: Whether the function waits for the action to be
        performed or does it asynchronously.
    """
    try:
        propagation_policy = 'Background' if asynchronous else 'Foreground'
        delete_options = V1DeleteOptions(
            propagation_policy=propagation_policy)
        current_k8s_batchv1_api_client.delete_namespaced_job(
            job.metadata.name, job.metadata.namespace, delete_options)
    except ApiException as e:
        logging.error(
            'An error has occurred while connecting to Kubernetes API Server'
            ' \n {}'.format(e))
        raise ComputingBackendSubmissionError(e.reason)


def start_watch_jobs_thread(JOB_DB):
    """Watch changes on job objects on kubernetes."""
    job_event_reader_thread = threading.Thread(target=k8s_watch_jobs,
                                               args=(JOB_DB,))
    job_event_reader_thread.daemon = True
    job_event_reader_thread.start()
