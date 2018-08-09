# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017 CERN.
#
# REANA is free software; you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# REANA is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# REANA; if not, write to the Free Software Foundation, Inc., 59 Temple Place,
# Suite 330, Boston, MA 02111-1307, USA.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization or
# submit itself to any jurisdiction.

"""Kubernetes wrapper."""

import json
import logging
import os
import time
import traceback

from flask import current_app as app
from kubernetes import client
from kubernetes import config as k8s_config
from kubernetes import watch
from kubernetes.client.models.v1_delete_options import V1DeleteOptions
from reana_db.database import Session
from reana_db.models import Job

from reana_job_controller import config, volume_templates


def create_api_client(api='BatchV1'):
    """Create Kubernetes API client using config.

    :param api: String which represents which Kubernetes API to spawn. By
        default BatchV1.
    :returns: Kubernetes python client object for a specific API i.e. BatchV1.
    """
    k8s_config.load_incluster_config()
    api_configuration = client.Configuration()
    api_configuration.verify_ssl = False
    if api == 'CoreV1':
        api_client = client.CoreV1Api()
    else:
        api_client = client.BatchV1Api()
    return api_client


def add_shared_volume(job):
    """Add shared CephFS volume to a given job spec.

    :param job: Kubernetes job spec.
    """
    storage_backend = os.getenv('REANA_STORAGE_BACKEND', 'LOCAL')
    if storage_backend == 'CEPHFS':
        volume = volume_templates.get_k8s_cephfs_volume(
            job['metadata']['namespace'])
    else:
        volume = volume_templates.get_k8s_hostpath_volume(
            job['metadata']['namespace'])
    mount_path = config.SHARED_FS_MAPPING['MOUNT_DEST_PATH']

    job['spec']['template']['spec']['containers'][0]['volumeMounts'].append(
        {'name': volume['name'], 'mountPath': mount_path}
    )
    job['spec']['template']['spec']['volumes'].append(volume)


def instantiate_job(job_id, docker_img, cmd, cvmfs_repos, env_vars, namespace,
                    shared_file_system, job_type):
    """Create Kubernetes job.

    :param job_id: Job uuid.
    :param docker_img: Docker image to run the job.
    :param cmd: Command provided to the docker container.
    :param cvmfs_repos: List of CVMFS repository names.
    :param env_vars: Dictionary representing environment variables
        as {'var_name': 'var_value'}.
    :param namespace: Job's namespace.
    :shared_file_system: Boolean which represents whether the job
        should have a shared file system mounted.
    :returns: Kubernetes job object if the job was successfuly created,
        None if not.
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
        add_shared_volume(job)

    if cvmfs_repos:
        for num, repo in enumerate(cvmfs_repos):
            volume = volume_templates.get_k8s_cvmfs_volume(namespace, repo)
            mount_path = volume_templates.get_cvmfs_mount_point(repo)

            volume['name'] += '-{}'.format(num)
            (job['spec']['template']['spec']['containers'][0]
                ['volumeMounts'].append(
                    {'name': volume['name'], 'mountPath': mount_path}
            ))
            job['spec']['template']['spec']['volumes'].append(volume)

    # add better handling
    try:
        api_response = \
            app.config['KUBERNETES_CLIENT'].create_namespaced_job(
                namespace=namespace, body=job)
        return api_response.to_str()
    except client.rest.ApiException as e:
        logging.debug("Error while connecting to Kubernetes API: {}".format(e))
    except Exception as e:
        logging.error(traceback.format_exc())
        logging.debug("Unexpected error: {}".format(e))


def watch_jobs(job_db):
    """Open stream connection to k8s apiserver to watch all jobs status.

    :param job_db: Dictionary which contains all current jobs.
    :param config: configuration to connect to k8s apiserver.
    """
    batchv1_api_client = create_api_client()
    corev1_api_client = create_api_client('CoreV1')
    while True:
        logging.debug('Starting a new stream request to watch Jobs')
        try:
            w = watch.Watch()
            for event in w.stream(
                    batchv1_api_client.list_job_for_all_namespaces):
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
                last_spawned_pod = corev1_api_client.list_namespaced_pod(
                    job.metadata.namespace,
                    label_selector='job-name={job_name}'.format(
                        job_name=job.metadata.name)).items[-1]
                logging.info('Grabbing pod {} logs...'.format(
                    last_spawned_pod.metadata.name))
                job_db[job.metadata.name]['log'] = \
                    corev1_api_client.read_namespaced_pod_log(
                        namespace=last_spawned_pod.metadata.namespace,
                        name=last_spawned_pod.metadata.name)
                # Store job logs
                try:
                    logging.info('Storing job logs: {}'.
                                 format(job_db[job.metadata.name]['log']))
                    Session.query(Job).filter_by(id_=job.metadata.name).\
                        update(dict(logs=job_db[job.metadata.name]['log']))
                    Session.commit()

                except Exception as e:
                    logging.debug('Could not retrieve'
                                  ' logs for object: {}'.
                                  format(last_spawned_pod))
                    logging.debug('Exception: {}'.format(str(e)))

                logging.info('Cleaning job {} ...'.format(
                    job.metadata.name))
                # Delete all depending pods.
                delete_options = V1DeleteOptions(
                    propagation_policy='Background')
                batchv1_api_client.delete_namespaced_job(
                    job.metadata.name, job.metadata.namespace, delete_options)
                job_db[job.metadata.name]['deleted'] = True
        except client.rest.ApiException as e:
            logging.debug(
                "Error while connecting to Kubernetes API: {}".format(e))
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.debug("Unexpected error: {}".format(e))
