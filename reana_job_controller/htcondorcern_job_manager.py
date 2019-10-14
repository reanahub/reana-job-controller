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
import re
import threading
import time
from shutil import copyfile

import classad
import htcondor
from flask import current_app
from reana_db.database import Session
from reana_db.models import Workflow
from retrying import retry

from reana_job_controller.job_manager import JobManager
from reana_job_controller.utils import initialize_krb5_token

thread_local = threading.local()


class HTCondorJobManagerCERN(JobManager):
    """CERN HTCondor job management."""

    MAX_NUM_RETRIES = 3
    """Maximum number of tries used for getting schedd, job submission and
    spooling output.
    """

    def __init__(self, docker_img=None, cmd=None, env_vars=None, job_id=None,
                 workflow_uuid=None, workflow_workspace=None,
                 cvmfs_mounts='false', shared_file_system=False,
                 job_name=None, kerberos=False):
        """Instanciate HTCondor job manager.

        :param docker_img: Docker image.
        :type docker_img: str
        :param cmd: Command to execute.
        :type cmd: list
        :param env_vars: Environment variables.
        :type env_vars: dict
        :param job_id: Unique job id.
        :type job_id: str
        :param workflow_uuid: Unique workflow id.
        :type workflow_uuid: str
        :param workflow_workspace: Workflow workspace path.
        :type workflow_workspace: str
        :param cvmfs_mounts: list of CVMFS mounts as a string.
        :type cvmfs_mounts: str
        :param shared_file_system: if shared file system is available.
        :type shared_file_system: bool
        :param job_name: Name of the job
        :type job_name: str
        """
        super(HTCondorJobManagerCERN, self).__init__(
            docker_img=docker_img, cmd=cmd,
            env_vars=env_vars, job_id=job_id,
            workflow_uuid=workflow_uuid,
            workflow_workspace=workflow_workspace,
            job_name=job_name)
        self.compute_backend = "HTCondor"
        self.cvmfs_mounts = cvmfs_mounts
        self.shared_file_system = shared_file_system
        self.workflow = self._get_workflow()

    @JobManager.execution_hook
    def execute(self):
        """Execute / submit a job with HTCondor."""
        os.chdir(self.workflow_workspace)
        initialize_krb5_token(workflow_uuid=self.workflow_uuid)
        job_ad = classad.ClassAd()
        job_ad['JobDescription'] = \
            self.workflow.get_full_workflow_name() + '_' + self.job_name
        job_ad['JobMaxRetries'] = 3
        job_ad['LeaveJobInQueue'] = classad.ExprTree(
            '(JobStatus == 4) && ((StageOutFinish =?= UNDEFINED) || '
            '(StageOutFinish == 0))')
        job_ad['DockerImage'] = self.docker_img
        job_ad['WantDocker'] = True
        job_ad['Cmd'] = './job_wrapper.sh'
        job_ad['Arguments'] = self._format_arguments()
        job_ad['Environment'] = self._format_env_vars()
        job_ad['Out'] = classad.ExprTree(
            'strcat("reana_job.", ClusterId, ".", ProcId, ".out")')
        job_ad['Err'] = classad.ExprTree(
            'strcat("reana_job.", ClusterId, ".", ProcId, ".err")')
        job_ad['log'] = classad.ExprTree(
            'strcat("reana_job.", ClusterId, ".err")')
        job_ad['ShouldTransferFiles'] = 'YES'
        job_ad['WhenToTransferOutput'] = 'ON_EXIT'
        job_ad['TransferInput'] = self._get_input_files()
        job_ad['TransferOutput'] = '.'
        job_ad['PeriodicRelease'] = classad.ExprTree('(HoldReasonCode == 35)')
        job_ad['MaxRunTime'] = 3600
        future = current_app.htcondor_executor.submit(self._submit, job_ad)
        clusterid = future.result()
        return clusterid

    def _replace_absolute_paths_with_relative(self, base_64_enconded_cmd):
        """Replace absolute with relative path."""
        relative_paths_command = None
        decoded_cmd = \
            base64.b64decode(base_64_enconded_cmd).decode('utf-8')
        if self.workflow_workspace in decoded_cmd:
            decoded_cmd = \
                decoded_cmd.replace(self.workflow_workspace + '/', '')
            relative_paths_command = \
                base64.b64encode(
                    decoded_cmd.encode('utf-8')).decode('utf-8')
        return relative_paths_command

    def _format_arguments(self):
        r"""Format HTCondor job execution arguments.

        input  - ['bash', '-c',
                  'cd /var/reana/users/00000000-0000-0000-0000-000000000000/
                       workflows/e4691f78-25aa-4f90-9c3d-6873a97bdf16 ;
                   python "code/helloworld.py" --inputfile "data/names.txt"
                           --outputfile "results/greetings.txt" --sleeptime 0']
        output - python \"code/helloworld.py\" --inputfile \"data/names.txt\"
                 --outputfile \"results/greetings.txt\" --sleeptime 0
        """
        if self.workflow.type_ == 'serial':
            arguments = re.sub(r'"', '\\"', " ".join(self.cmd[2].split()[3:]))
        elif self.workflow.type_ == 'cwl':
            arguments = self.cmd[2].replace(self.workflow_workspace,
                                            '$_CONDOR_JOB_IWD')
        elif self.workflow.type_ == 'yadage':
            if 'base64' in ' '.join(self.cmd):
                base_64_encoded_cmd = self.cmd[2].split('|')[0].split()[1]
                base_64_encoded_cmd = \
                    self._replace_absolute_paths_with_relative(
                        base_64_encoded_cmd) or base_64_encoded_cmd
                arguments = \
                    'echo {}|base64 -d|bash'.format(base_64_encoded_cmd)
            else:
                if self.workflow_workspace in self.cmd[2]:
                    arguments = \
                        self.cmd[2].replace(self.workflow_workspace + '/', '')
                    arguments = re.sub(r'"', '\"', arguments)
        return "{}".format(arguments)

    def _format_env_vars(self):
        """Return job env vars in job description format."""
        job_env = ''
        for key, value in self.env_vars.items():
            job_env += " {0}={1}".format(key, value)
        return job_env

    def _get_workflow(self):
        """Get workflow from db."""
        workflow = Session.query(Workflow).filter_by(id_=self.workflow_uuid).\
            one_or_none()
        if workflow:
            return workflow
        else:
            pass

    def _get_input_files(self):
        """Get files and dirs from workflow space."""
        input_files = []
        self._copy_wrapper_file()
        forbidden_files = \
            ['.job.ad', '.machine.ad', '.chirp.config']
        skip_extensions = ('.err', '.log', '.out')
        for item in os.listdir(self.workflow_workspace):
            if item not in forbidden_files and \
               not item.endswith(skip_extensions):
                input_files.append(item)

        return ",".join(input_files)

    def _copy_wrapper_file(self):
        """Copy job wrapper file to workspace."""
        try:
            copyfile('/etc/job_wrapper.sh',
                     os.path.join(self.workflow_workspace + '/' +
                                  'job_wrapper.sh'))
        except Exception as e:
            logging.error("Failed to copy job wrapper file: {0}".format(e),
                          exc_info=True)
            raise e

    @retry(stop_max_attempt_number=MAX_NUM_RETRIES)
    def _submit(self, job_ad):
        """Execute submission transaction."""
        try:
            ads = []
            schedd = HTCondorJobManagerCERN._get_schedd()
            logging.info('Submiting job - {}'.format(job_ad))
            clusterid = schedd.submit(job_ad, 1, True, ads)
            HTCondorJobManagerCERN._spool_input(ads)
            return clusterid
        except Exception as e:
            logging.error("Submission failed: {0}".format(e), exc_info=True)
            time.sleep(10)

    @retry(stop_max_attempt_number=MAX_NUM_RETRIES)
    def _spool_input(ads):
        try:
            schedd = HTCondorJobManagerCERN._get_schedd()
            logging.info('Spooling job inputs - {}'.format(ads))
            schedd.spool(ads)
        except Exception as e:
            logging.error("Spooling failed: {0}".format(e), exc_info=True)
            time.sleep(10)

    @retry(stop_max_attempt_number=MAX_NUM_RETRIES)
    def _get_schedd():
        """Find and return the HTCondor schedd."""
        try:
            schedd = getattr(thread_local, 'MONITOR_THREAD_SCHEDD', None)
            if schedd is None:
                setattr(thread_local,
                        'MONITOR_THREAD_SCHEDD',
                        htcondor.Schedd())
            logging.info("Getting schedd: {}".format(
                thread_local.MONITOR_THREAD_SCHEDD))
            return thread_local.MONITOR_THREAD_SCHEDD
        except Exception as e:
            logging.error("Can't locate schedd: {0}".format(e), exc_info=True)
            time.sleep(10)

    def stop(backend_job_id):
        """Stop HTCondor job execution."""
        try:
            schedd = HTCondorJobManagerCERN._get_schedd()
            schedd.act(
                htcondor.JobAction.Remove,
                'ClusterId=={}'.format(backend_job_id))
        except Exception as e:
            logging.error(e, exc_info=True)

    @retry(stop_max_attempt_number=MAX_NUM_RETRIES)
    def spool_output(backend_job_id):
        """Transfer job output."""
        try:
            schedd = HTCondorJobManagerCERN._get_schedd()
            logging.info("Spooling jobs {} output.".format(backend_job_id))
            schedd.retrieve("ClusterId == {}".format(backend_job_id))
        except Exception as e:
            logging.error(e, exc_info=True)
            time.sleep(10)

    def get_logs(backend_job_id, workspace):
        """Return job logs if log files are present."""
        stderr_file = \
            os.path.join(workspace,
                         'reana_job.' + str(backend_job_id) + '.0.err')
        stdout_file = \
            os.path.join(workspace,
                         'reana_job.' + str(backend_job_id) + '.0.out')
        log_files = [stderr_file, stdout_file]
        job_log = ''
        try:
            for file in log_files:
                with open(file, "r") as log_file:
                    job_log += log_file.read()
            return job_log
        except Exception as e:
            msg = 'Job logs of {} were not found. {}'.format(backend_job_id, e)
            logging.error(msg, exc_info=True)
            return msg

    def find_job_in_history(backend_job_id):
        """Return job if present in condor history."""
        schedd = HTCondorJobManagerCERN._get_schedd()
        ads = ['ClusterId', 'JobStatus', 'ExitCode', 'RemoveReason']
        condor_it = schedd.history('ClusterId == {0}'.format(
            backend_job_id), ads, match=1)
        try:
            condor_job = next(condor_it)
            return condor_job
        except Exception:
            # Did not match to any job in the history  yet
            return None
