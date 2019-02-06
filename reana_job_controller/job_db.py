# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller job database."""

from reana_commons.utils import calculate_hash_of_dir, calculate_job_input_hash
from reana_db.database import Session
from reana_db.models import JobCache

JOB_DB = {}


def retrieve_job(job_id):
    """Retrieve job from DB by id.

    :param job_id: UUID which identifies the job to be retrieved.
    :returns: Job object identified by `job_id`.
    """
    job = JOB_DB[job_id]
    return {
        "cmd": job['cmd']
        if job.get('cmd') else '',
        "cvmfs_mounts": job['cvmfs_mounts']
        if job.get('cvmfs_mounts') else '',
        "docker_img": job['docker_img'],
        "experiment": job['experiment'],
        "job_id": job['job_id'],
        "max_restart_count": job['max_restart_count'],
        "restart_count": job['restart_count'],
        "status": job['status']
    }


def retrieve_k8s_job(job_id):
    """Retrieve the Kubernetes job.

    :param job_id: String which represents the ID of the job.
    :returns: The :class:`kubernetes.client.models.v1_job.V1Job` object.
    """
    return JOB_DB[job_id]['obj']


def retrieve_all_jobs():
    """Retrieve all jobs in the DB.

    :return: A list with all current job objects.
    """
    job_list = []
    for job_id in JOB_DB:
        job = JOB_DB[job_id]
        job_list.append({
            job_id: {
                "cmd": job['cmd']
                if job.get('cmd') else '',
                "cvmfs_mounts": job['cvmfs_mounts']
                if job.get('cvmfs_mounts') else [],
                "docker_img": job['docker_img'],
                "experiment": job['experiment'],
                "job_id": job['job_id'],
                "max_restart_count": job['max_restart_count'],
                "restart_count": job['restart_count'],
                "status": job['status']
            }
        })
    return job_list


def job_is_cached(job_spec, workflow_json, workflow_workspace):
    """Check if job result exists in the cache."""
    input_hash = calculate_job_input_hash(job_spec, workflow_json)
    workspace_hash = calculate_hash_of_dir(workflow_workspace)
    if workspace_hash == -1:
        return None

    cached_job = Session.query(JobCache).filter_by(
        parameters=input_hash,
        workspace_hash=workspace_hash).first()
    if cached_job:
        return {'result_path': cached_job.result_path,
                'job_id': cached_job.job_id}
    else:
        return None


def job_exists(job_id):
    """Check if the job exists in the DB.

    :param job_id: UUID which identifies the job.
    :returns: Boolean representing if the job exists.
    """
    return job_id in JOB_DB


def retrieve_job_logs(job_id):
    """Retrieve job's logs.

    :param job_id: UUID which identifies the job.
    :returns: Job's logs.
    """
    return JOB_DB[job_id].get('log')
