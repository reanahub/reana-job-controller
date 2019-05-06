# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""CERN HTCondor Job Manager."""

import base64
import logging
import os
import pathlib
import re
import time
import traceback
import uuid

import fs
from flask import current_app
from kubernetes import client
from kubernetes.client.rest import ApiException
from reana_commons.config import K8S_DEFAULT_NAMESPACE
from reana_commons.k8s.api_client import current_k8s_batchv1_api_client
from reana_commons.k8s.volumes import get_shared_volume
from reana_commons.utils import format_cmd
from reana_db.database import Session
from reana_db.models import Workflow

from reana_job_controller.job_manager import JobManager


class HTCondorJobManagerCERN(JobManager):
    """CERN HTCondor job management."""

    def __init__(self, docker_img=None, cmd=None, env_vars=None, job_id=None,
                 workflow_uuid=None, workflow_workspace=None,
                 cvmfs_mounts='false', shared_file_system=False):
        """Instanciate HTCondor job manager.

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
        super(HTCondorJobManagerCERN, self).__init__(
            docker_img=docker_img, cmd=cmd,
            env_vars=env_vars, job_id=job_id,
            workflow_uuid=workflow_uuid)
        self.backend = "HTCondor"
        self.workflow_workspace = workflow_workspace
        self.cvmfs_mounts = cvmfs_mounts
        self.shared_file_system = shared_file_system
        self.workflow = self._get_workflow()
        self.keytab_file, self.cern_username = self._find_keytab()

    @JobManager.execution_hook
    def execute(self):
        """Execute a kubernetes job responsible for HTCondor job submission."""
        submission_file = 'job_{}.sub'.format(time.time())
        check_cmd_exit_code = \
            'if [ $? -ne 0 ]; then echo "command failed"; exit 1; fi;'
        self._dump_condor_submission_file(submission_file)
        add_user_cmd = \
            'useradd -Ms /bin/bash $CONDOR_USER;{}'.format(check_cmd_exit_code)
        cp_job_wrapper_cmd = \
            'cp /job_wrapper.sh {};{}'.format(self.workflow_workspace,
                                              check_cmd_exit_code)
        chown_worksapce_cmd = \
            'sudo chown -R $CONDOR_USER {};{}'.format(self.workflow_workspace,
                                                      check_cmd_exit_code)
        go_to_workspace_cmd = 'cd {};{}'.format(self.workflow_workspace,
                                                check_cmd_exit_code)
        authentication_cmd = \
            'kinit -V -kt {} {}; {}'.format(self.keytab_file,
                                            self.cern_username,
                                            check_cmd_exit_code)
        htcondor_job_submission_cmd = \
            ('job_id=$(condor_submit INPUTS={} -spool -terse {} | '
             'cut -f 1 -d " " ); {}'.format(self._get_input_files(),
                                            submission_file,
                                            check_cmd_exit_code))
        get_htcondor_job_status_cmd = \
            'job_status="eval condor_q $job_id -format %d JobStatus";'
        htcondor_job_tracking_cmd = \
            ('while [[ $($job_status) != "4" ]];'
             ' do echo "JOB $job_id is still running"; sleep 30; done;')
        add_user_cmd = 'useradd -Ms /bin/bash $CONDOR_USER;'
        get_htcondor_job_output_cmd = 'condor_transfer_data $job_id;'
        htcondor_job_wrapper_cmd = \
            ["{}{}{} sudo -u $CONDOR_USER /bin/bash -c '{}{}{}{}{}{}'".format(
                add_user_cmd,
                cp_job_wrapper_cmd,
                chown_worksapce_cmd,
                go_to_workspace_cmd,
                authentication_cmd,
                htcondor_job_submission_cmd,
                get_htcondor_job_status_cmd,
                htcondor_job_tracking_cmd,
                get_htcondor_job_output_cmd
            )]
        submission_job = self._create_job_spec(
            command=htcondor_job_wrapper_cmd,
            env_vars=[{'name': 'CONDOR_USER',
                      'value': self.cern_username}])
        try:
            self._clean_workspace()
            api_response = \
                current_k8s_batchv1_api_client.create_namespaced_job(
                    namespace=K8S_DEFAULT_NAMESPACE,
                    body=submission_job)
            return api_response.metadata.labels['job-name']
        except ApiException as e:
            logging.debug("Error while connecting to Kubernetes"
                          " API: {}".format(e))
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.debug("Unexpected error: {}".format(e))

    def _create_job_spec(self, name=None, command=None, image=None,
                         env_vars=None):
        """Create a spec of kubernetes job for condor job submission.

        :param name: Name of the job.
        :type name: str
        :param image: Docker image to use for condor job submission.
        :type image: str
        :param command: List of commands to run on the given job.
        :type command: list
        :param env_vars: List of environment variables (dictionaries) to
            set on execution container.
        :type list: list
        """
        name = name or self._generate_htcondor_submitter_name()
        image = image or current_app.config['HTCONDOR_SUBMISSION_JOB_IMG']
        command = command or []
        env_vars = env_vars or []
        command = format_cmd(command)
        workflow_metadata = client.V1ObjectMeta(name=name)
        job = client.V1Job()
        job.api_version = 'batch/v1'
        job.kind = 'Job'
        job.metadata = workflow_metadata
        spec = client.V1JobSpec(
            template=client.V1PodTemplateSpec())
        spec.template.metadata = workflow_metadata
        container = client.V1Container(name=name,
                                       image=image,
                                       image_pull_policy='IfNotPresent',
                                       env=[],
                                       volume_mounts=[],
                                       command=['/bin/bash'],
                                       args=['-c'] + command
                                       )
        container.env.extend(env_vars)
        volume_mount, volume = get_shared_volume(
            self.workflow_workspace,
            current_app.config['SHARED_VOLUME_PATH_ROOT'])
        container.volume_mounts = [volume_mount]
        spec.template.spec = client.V1PodSpec(containers=[container])
        spec.template.spec.volumes = [volume]
        job.spec = spec
        job.spec.template.spec.restart_policy = 'Never'
        job.spec.ttl_seconds_after_finished = \
            current_app.config['HTCONDOR_SUBMITTER_POD_CLEANUP_THRESHOLD']
        job.spec.active_deadline_seconds = \
            current_app.config['HTCONDOR_SUBMITTER_POD_MAX_LIFETIME']
        job.spec.backoff_limit = 0
        return job

    def _dump_condor_submission_file(self, submission_file_name):
        """Dump condor submission file to workspace.

        :param submission_file_name: Name of the condor job submission file
        :type submission_file_name: str
        """
        job_template = """
        max_retries   = 3
        universe      = docker
        docker_image  = {docker_img}
        executable    = job_wrapper.sh
        arguments     = {arguments}
        environment   = {env_vars}
        output        = reana_job.$(ClusterId).$(ProcId).out
        error         = reana_job.$(ClusterId).$(ProcId).err
        log           = reana_job.$(ClusterId).log
        should_transfer_files = YES
        if defined INPUTS
            transfer_input_files = $(INPUTS)
        else
            transfer_input_files  = {input_files}
        endif
        transfer_output_files = ./
        periodic_release = (HoldReasonCode == 35)
        queue
        """.format(docker_img=self.docker_img,
                   env_vars=self._format_env_vars(),
                   arguments=self._format_arguments(),
                   input_files=self.workflow_workspace + '/',
                   # output_files=self._get_output_files()
                   )
        submission_file = \
            os.path.join(self.workflow_workspace, submission_file_name)
        f = open(submission_file, "w")
        f.write(job_template)
        f.close()

    def _format_arguments(self):
        """Format HTCondor job execution arguments."""
        if self.workflow.type_ == 'serial' or self.workflow.type_ == 'cwl':
            arguments = re.sub(r'"', '\\"', " ".join(self.cmd[2].split()[3:]))
        elif self.workflow.type_ == 'yadage':
            base_64_encoded_cmd = self.cmd[2].split('|')[0].split()[1]
            decoded_cmd = base64.b64decode(base_64_encoded_cmd).decode('utf-8')
            if self.workflow_workspace in decoded_cmd:
                decoded_cmd = \
                    decoded_cmd.replace(self.workflow_workspace + '/', '')
            base_64_encoded_cmd = \
                base64.b64encode(decoded_cmd.encode('utf-8')).decode('utf-8')
            arguments = 'echo {}|base64 -d|bash'.format(base_64_encoded_cmd)
        return "{}".format(arguments)

    def _get_output_files(self):
        """Return expected output path of a workflow."""
        workflow = Session.query(Workflow).filter_by(id_=self.workflow_uuid).\
            one_or_none()
        output_dirs = set()
        for path in workflow.reana_specification['outputs']['files']:
            output_dirs.add(str(pathlib.Path(path).parents[0]))
        return ' '.join(output_dirs)

    def _format_env_vars(self):
        """Return job env vars in job description format."""
        job_env = ''
        for key, value in self.env_vars:
            job_env += " {0}={1}".format(key, value)
        return job_env

    def _generate_htcondor_submitter_name(self):
        """Generate the name for HTCondor sumbmission job."""
        return 'htcondor-submitter-' + str(uuid.uuid4())

    def _get_workflow(self):
        """Get workflow from db."""
        workflow = Session.query(Workflow).filter_by(id_=self.workflow_uuid).\
            one_or_none()
        if workflow:
            return workflow
        else:
            pass

    def _clean_workspace(self):
        """Delete condor files."""
        files_to_delete = ['.job.ad', '.machine.ad', '.chirp.config']
        for file in files_to_delete:
            with fs.open_fs(self.workflow_workspace) as workspace:
                try:
                    workspace.remove(file)
                except fs.errors.FileExpected:
                    pass
                except fs.errors.ResourceNotFound:
                    pass

    def _get_input_files(self):
        """Get files and dirs from workflow space."""
        input_files = []
        forbidden_files = \
            ['.job.ad', '.machine.ad', '.chirp.config', self.keytab_file]
        for item in os.listdir(self.workflow_workspace):
            if item not in forbidden_files:
                input_files.append(item)

        return ",".join(input_files)

    def _find_keytab(self):
        """Return keytab filename and CERN username."""
        workspace = fs.open_fs(self.workflow_workspace)
        keytab_file = ''
        cern_username = ''
        for file in workspace.glob("*.keytab"):
            keytab_file = file.info.name
            cern_username = file.info.stem
            break
        if not keytab_file:
            msg = '*.keytab file was not found'
            raise Exception(msg)
        return keytab_file, cern_username
