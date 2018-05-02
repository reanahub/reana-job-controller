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

import logging
import os
import time

import pykube
import docker
from flask import current_app as app

from reana_job_controller import volume_templates


def create_api_client(config):
    """Create pykube HTTPClient using config."""
    api_client = pykube.HTTPClient(config)
    api_client.session.verify = False
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
    mount_path = volume_templates.REANA_STORAGE_MOUNT_PATH

    job['spec']['template']['spec']['containers'][0]['volumeMounts'].append(
        {'name': volume['name'], 'mountPath': mount_path}
    )
    job['spec']['template']['spec']['volumes'].append(volume)


def instantiate_job(job_id, docker_img, cmd, cvmfs_repos, env_vars, namespace,
                    shared_file_system, job_type='kube'):
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
    if job_type == 'docker':
        client = docker.from_env()
        if cmd:
            import shlex
            command = shlex.split(cmd)
        result = client.containers.run(docker_img,
                                       command=command,
                                       environment=env_vars,
                                       detach=True)
        return result

    job = {
        'kind': 'Job',
        'apiVersion': 'batch/v1',
        'metadata': {
            'name': job_id,
            'namespace': namespace
        },
        'spec': {
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
                    'restartPolicy': 'OnFailure'
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
        job_obj = pykube.Job(app.config['PYKUBE_CLIENT'], job)
        job_obj.create()
        return job_obj
    except pykube.exceptions.HTTPError:
        return None


def watch_jobs(job_db, config):
    """Open stream connection to k8s apiserver to watch all jobs status.

    :param job_db: Dictionary which contains all current jobs.
    :param config: configuration to connect to k8s apiserver.
    """
    api_client = create_api_client(config)
    while True:
        logging.debug('Starting a new stream request to watch Jobs')
        stream = pykube.Job.objects(
            api_client).filter(namespace=pykube.all).watch()
        for event in stream:
            logging.info('New Job event received')
            job = event.object
            unended_jobs = [j for j in job_db.keys()
                            if not job_db[j]['deleted']]

            if job.name in unended_jobs and event.type == 'DELETED':
                while not job_db[job.name].get('pod'):
                    time.sleep(5)
                    logging.warn(
                        'Job {} Pod still not known'.format(job.name)
                    )
                pod = job_db[job.name].get('pod')
                while job.exists():
                    logging.warn(
                        'Waiting for Job {} to be cleaned'.format(
                            job.name
                        )
                    )
                    time.sleep(5)
                logging.info(
                    'Getting {} logs'.format(pod.name)
                )
                job_db[job.name]['log'] = pod.logs()
                logging.info(
                    'Deleting {}\'s pod -> {}'.format(
                        job.name, job_db[job.name]['pod'].name
                    )
                )
                job_db[job.name]['pod'].delete()
                job_db[job.name]['deleted'] = True

            elif (job.name in unended_jobs and
                  job.obj['status'].get('succeeded')):
                logging.info(
                    'Job {} successfuly ended. Cleaning...'.format(job.name)
                )
                job_db[job.name]['status'] = 'succeeded'
                job.delete()

            # with the current k8s implementation this is never
            # going to happen...
            elif job.name in unended_jobs and job.obj['status'].get('failed'):
                logging.info('Job {} failed. Cleaning...'.format(job.name))
                job_db[job['metadata']['name']]['status'] = 'failed'
                job.delete()


def watch_pods(job_db, config):
    """Open stream connection to k8s apiserver to watch all pods status.

    :param job_db: Dictionary which contains all current jobs.
    :param config: configuration to connect to k8s apiserver.
    """
    api_client = create_api_client(config)
    while True:
        logging.info('Starting a new stream request to watch Pods')
        stream = pykube.Pod.objects(
            api_client).filter(namespace=pykube.all).watch()
        for event in stream:
            logging.info('New Pod event received')
            pod = event.object
            unended_jobs = [j for j in job_db.keys()
                            if not job_db[j]['deleted'] and
                            job_db[j]['status'] != 'failed']
            # FIXME: watch out here, if they change the naming convention at
            # some point the following line won't work. Get job name from API.
            job_name = '-'.join(pod.name.split('-')[:-1])
            # Store existing job pod if not done yet
            if job_name in job_db and not job_db[job_name].get('pod'):
                # Store job's pod
                logging.info(
                    'Storing {} as Job {} Pod'.format(pod.name, job_name)
                )
                job_db[job_name]['pod'] = pod
            # Take note of the related Pod
            if job_name in unended_jobs:
                try:
                    restarts = (pod.obj['status']['containerStatuses'][0]
                                ['restartCount'])
                    exit_code = (pod.obj['status']
                                 ['containerStatuses'][0]
                                 ['state'].get('terminated', {})
                                 .get('exitCode'))
                    logging.info(
                        pod.obj['status']['containerStatuses'][0]['state'].
                        get('terminated', {})
                    )

                    logging.info(
                        'Updating Pod {} restarts to {}'.format(
                            pod.name, restarts
                        )
                    )

                    job_db[job_name]['restart_count'] = restarts

                    if restarts >= job_db[job_name]['max_restart_count'] and \
                       exit_code != 0:

                        logging.info(
                            'Job {} reached max restarts...'.format(job_name)
                        )

                        logging.info(
                            'Getting {} logs'.format(pod.name)
                        )
                        job_db[job_name]['log'] = pod.logs()
                        logging.info(
                            'Cleaning Job {}'.format(job_name)
                        )
                        job_db[job_name]['status'] = 'failed'
                        job_db[job_name]['obj'].delete()

                except KeyError as e:
                    logging.debug('Skipping event because: {}'.format(e))
                    logging.debug(
                        'Event: {}\nObject:\n{}'.format(event.type, pod.obj)
                    )
