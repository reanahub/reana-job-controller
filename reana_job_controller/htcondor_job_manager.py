# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Kubernetes Job Manager."""

import ast
import logging
import traceback
import uuid
import htcondor
import classad
import os
from retrying import retry
import re

from kubernetes.client.rest import ApiException
from reana_commons.config import CVMFS_REPOSITORIES, K8S_DEFAULT_NAMESPACE

# What's defined in these? Add stuff for condor? i.e. get_schedd() etc
#from reana_commons.k8s.api_client import current_k8s_batchv1_api_client
#from reana_commons.k8s.volumes import get_k8s_cvmfs_volume, get_shared_volume

from reana_job_controller.config import (MAX_JOB_RESTARTS,
                                         SHARED_VOLUME_PATH_ROOT)
from reana_job_controller.errors import ComputingBackendSubmissionError
from reana_job_controller.job_manager import JobManager

def detach(f):
    """Decorator for creating a forked process"""

    def fork(*args, **kwargs):
        pid = os.fork()
        if pid == 0:
            try:
                os.setuid(int(os.environ.get('VC3USERID')))
                f(*args, **kwargs)
            finally:
                os._exit(0)

    return fork

@retry(stop_max_attempt_number=MAX_JOB_RESTARTS)
@detach
def submit(schedd, sub):
    try:
        with schedd.transaction() as txn:
            clusterid = sub.queue(txn)
    except Exception as e:
        logging.debug("Error submission: {0}".format(e))
        raise(Exception)

    return clusterid

def get_input_files(workflow_workspace):
    """Get files from workflow space
    :param workflow_workspace: Workflow directory
    """
    # First, get list of input files
    input_files = []
    for root, dirs, files in os.walk(workflow_workspace):
        for filename in files:
           input_files.append(os.path.join(root, filename))
    
    return ",".join(input_files)

def get_schedd():
    """Find and return the HTCondor sched.
    :returns: htcondor schedd object."""

    # Getting remote scheduler
    schedd_ad = classad.ClassAd()
    schedd_ad["MyAddress"] = os.environ.get("HTCONDOR_ADDR", None) 
    schedd = htcondor.Schedd(schedd_ad)
    return schedd

class HTCondorJobManager(JobManager):
    """HTCondor job management."""

    def __init__(self, docker_img='', cmd='', env_vars={}, job_id=None,
                 workflow_uuid=None, workflow_workspace=None,
                 cvmfs_mounts='false', shared_file_system=False):
        """Instantiate HTCondor job manager.

        :param docker_img: Docker image.
        :type docker_img: str
        :param cmd: Command to execute.
        :type cmd: list
        :param env_vars: Environment variables.
        :type env_vars: dict
        :param job_id: Unique job id.
        :type job_id: str
        :param workflow_id: Unique workflow id.
        :type workflow_id: str
        :param workflow_workspace: Workflow workspace path.
        :type workflow_workspace: str
        :param cvmfs_mounts: list of CVMFS mounts as a string.
        :type cvmfs_mounts: str
        :param shared_file_system: if shared file system is available.
        :type shared_file_system: bool
        """
        self.docker_img = docker_img or ''
        self.cmd = cmd or ''
        self.env_vars = env_vars or {}
        self.job_id = job_id
        self.workflow_uuid = workflow_uuid
        self.backend = "HTCondor"
        self.workflow_workspace = workflow_workspace
        self.cvmfs_mounts = cvmfs_mounts
        self.shared_file_system = shared_file_system
        self.schedd = get_schedd()


    @JobManager.execution_hook
    def execute(self):
        print('docker image = {0}, cmd = {1}'.format(self.docker_img, self.cmd))
        """Execute / submit a job with HTCondor."""
        sub = htcondor.Submit()
        sub['executable'] = '/code/files/job_wrapper.sh'
        # condor arguments require double quotes to be escaped
        sub['arguments'] = 'exec --home .{0}:{0} docker://{1} {2}'.format(self.workflow_workspace,
                self.docker_img, re.sub(r'"', '\\"', self.cmd))
        sub['Output'] = '/tmp/$(Cluster)-$(Process).out'
        sub['Error'] = '/tmp/$(Cluster)-$(Process).err'
        sub['transfer_input_files'] = get_input_files(self.workflow_workspace)
        sub['InitialDir'] = '/tmp'
        sub['+WantIOProxy'] = 'true'
        job_env = 'reana_workflow_dir={0}'.format(self.workflow_workspace)
        for key, value in self.env_vars.items():
            job_env += '; {0}={1}'.format(key, value)
        sub['environment'] = job_env
        clusterid = submit(self.schedd, sub)

        return clusterid


    def stop(self, backend_job_id, asynchronous=True):
        """Stop HTCondor job execution.

        :param backend_job_id: HTCondor job id.
        :param asynchronous: Ignored.
        """
        self.schedd.act(htcondor.JobAction.Remove, 'ClusterId==%d' % backend_job_id)


    def add_shared_volume(self, job):
        """Add shared CephFS volume to a given job.
        """
        pass #Not Implemented yet
