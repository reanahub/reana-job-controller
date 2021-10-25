# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""CERN Slurm Job Manager."""

import base64
import logging
import os
from stat import S_ISDIR

from reana_job_controller.job_manager import JobManager
from reana_job_controller.utils import SSHClient, initialize_krb5_token


class SlurmJobManagerCERN(JobManager):
    """Slurm job management."""

    SLURM_WORKSAPCE_PATH = ""
    """Absolute path inside slurm head node used for submission."""
    REANA_WORKSPACE_PATH = ""
    """Absolute REANA workspace path."""
    SLURM_HEADNODE_HOSTNAME = os.getenv("SLURM_HOSTNAME", "hpc-batch.cern.ch")
    """Hostname of SLURM head-node used for job management via SSH."""
    SLURM_HEADNODE_PORT = os.getenv("SLURM_CLUSTER_PORT", "22")
    """Port of SLURM head node."""
    SLURM_PARTITION = os.getenv("SLURM_PARTITION", "batch-short")
    """Default slurm partition."""
    SLURM_HOME_PATH = os.getenv("SLURM_HOME_PATH", "")
    """Default SLURM home path."""

    def __init__(
        self,
        docker_img=None,
        cmd=None,
        prettified_cmd=None,
        env_vars=None,
        workflow_uuid=None,
        workflow_workspace=None,
        cvmfs_mounts="false",
        shared_file_system=False,
        job_name=None,
        kerberos=False,
        kubernetes_uid=None,
        unpacked_img=False,
    ):
        """Instanciate Slurm job manager.

        :param docker_img: Docker image.
        :type docker_img: str
        :param cmd: Command to execute.
        :type cmd: list
        :param prettified_cmd: pretified version of command to execute.
        :type prettified_cmd: str
        :param env_vars: Environment variables.
        :type env_vars: dict
        :param workflow_id: Unique workflow id.
        :type workflow_id: str
        :param workflow_workspace: Workflow workspace path.
        :type workflow_workspace: str
        :param cvmfs_mounts: list of CVMFS mounts as a string.
        :type cvmfs_mounts: str
        :param shared_file_system: if shared file system is available.
        :type shared_file_system: bool
        :param job_name: Name of the job
        :type job_name: str
        """
        super(SlurmJobManagerCERN, self).__init__(
            docker_img=docker_img,
            cmd=cmd,
            prettified_cmd=prettified_cmd,
            env_vars=env_vars,
            workflow_uuid=workflow_uuid,
            job_name=job_name,
        )
        self.compute_backend = "Slurm"
        self.workflow_workspace = workflow_workspace
        self.cvmfs_mounts = cvmfs_mounts
        self.shared_file_system = shared_file_system
        self.job_file = "job.sh"
        self.job_description_file = "job_description.sh"

    def _transfer_inputs(self):
        """Transfer inputs to SLURM submit node."""
        stdout = self.slurm_connection.exec_command("pwd")
        self.slurm_home_path = SlurmJobManagerCERN.SLURM_HOME_PATH or stdout.rstrip()
        SlurmJobManagerCERN.SLURM_WORKSAPCE_PATH = os.path.join(
            self.slurm_home_path, self.workflow_workspace[1:]
        )
        SlurmJobManagerCERN.REANA_WORKSPACE_PATH = self.workflow_workspace
        self.slurm_connection.exec_command(
            "mkdir -p {}".format(SlurmJobManagerCERN.SLURM_WORKSAPCE_PATH)
        )
        sftp = self.slurm_connection.ssh_client.open_sftp()
        os.chdir(self.workflow_workspace)
        for dirpath, dirnames, filenames in os.walk(self.workflow_workspace):
            try:
                sftp.mkdir(os.path.join(self.slurm_home_path, dirpath[1:]))
            except Exception:
                pass
            for file in filenames:
                sftp.put(
                    os.path.join(dirpath, file),
                    os.path.join(self.slurm_home_path, dirpath[1:], file),
                )

    @JobManager.execution_hook
    def execute(self):
        """Execute / submit a job with Slurm."""
        self.cmd = self._encode_cmd(self.cmd)
        initialize_krb5_token(workflow_uuid=self.workflow_uuid)
        self.slurm_connection = SSHClient(
            hostname=SlurmJobManagerCERN.SLURM_HEADNODE_HOSTNAME,
            port=SlurmJobManagerCERN.SLURM_HEADNODE_PORT,
        )
        self._transfer_inputs()
        self._dump_job_file()
        self._dump_job_submission_file()
        stdout = self.slurm_connection.exec_command(
            "cd {} && sbatch --parsable {}".format(
                SlurmJobManagerCERN.SLURM_WORKSAPCE_PATH, self.job_description_file
            )
        )
        backend_job_id = stdout.rstrip()
        return backend_job_id

    def _dump_job_submission_file(self):
        """Dump job submission file to the Slurm submit node."""
        job_template = (
            "#!/bin/bash \n"
            "#SBATCH --job-name={job_name} \n"
            "#SBATCH --output=reana_job.%j.out \n"
            "#SBATCH --error=reana_job.%j.err \n"
            "#SBATCH --partition {partition} \n"
            "#SBATCH --time 60 \n"
            "export PATH=$PATH:/usr/sbin \n"
            "srun {command}"
        ).format(
            partition=SlurmJobManagerCERN.SLURM_PARTITION,
            job_name=self.job_name,
            command=self._wrap_singularity_cmd(),
        )
        self.slurm_connection.exec_command(
            'cd {} && job="{}" && echo "$job"> {}'.format(
                SlurmJobManagerCERN.SLURM_WORKSAPCE_PATH,
                job_template,
                self.job_description_file,
            )
        )

    def _dump_job_file(self):
        """Dump job file."""
        job_template = "#!/bin/bash \n{}".format(self.cmd)
        self.slurm_connection.exec_command(
            'cd {} && job="{}" && echo "$job" > {} && chmod +x {}'.format(
                SlurmJobManagerCERN.SLURM_WORKSAPCE_PATH,
                job_template,
                self.job_file,
                self.job_file,
            )
        )

    def _encode_cmd(self, cmd):
        """Encode base64 cmd."""
        encoded_cmd = base64.b64encode(cmd.encode("utf-8")).decode("utf-8")
        return "echo {}|base64 -d|bash".format(encoded_cmd)

    def _wrap_singularity_cmd(self):
        """Wrap command in singulrity."""
        base_singularity_cmd = (
            "singularity exec -B {SLURM_WORKSAPCE}:{REANA_WORKSPACE}"
            " docker://{DOCKER_IMG} {CMD}".format(
                SLURM_WORKSAPCE=SlurmJobManagerCERN.SLURM_WORKSAPCE_PATH,
                REANA_WORKSPACE=SlurmJobManagerCERN.REANA_WORKSPACE_PATH,
                DOCKER_IMG=self.docker_img,
                CMD="./" + self.job_file,
            )
        )
        return base_singularity_cmd

    def get_outputs():
        """Transfer job outputs to REANA."""
        os.chdir(SlurmJobManagerCERN.REANA_WORKSPACE_PATH)
        slurm_connection = SSHClient()
        sftp = slurm_connection.ssh_client.open_sftp()
        SlurmJobManagerCERN._download_dir(
            sftp,
            SlurmJobManagerCERN.SLURM_WORKSAPCE_PATH,
            SlurmJobManagerCERN.REANA_WORKSPACE_PATH,
        )
        sftp.close()

    def _download_dir(sftp, remote_dir, local_dir):
        """Download remote directory content."""
        os.path.exists(local_dir) or os.makedirs(local_dir)
        dir_items = sftp.listdir_attr(remote_dir)
        for item in dir_items:
            remote_path = os.path.join(remote_dir, item.filename)
            local_path = os.path.join(local_dir, item.filename)
            if S_ISDIR(item.st_mode):
                SlurmJobManagerCERN._download_dir(sftp, remote_path, local_path)
            else:
                sftp.get(remote_path, local_path)

    def get_logs(backend_job_id, workspace):
        """Return job logs if log files are present."""
        stderr_file = os.path.join(
            workspace, "reana_job." + str(backend_job_id) + ".err"
        )
        stdout_file = os.path.join(
            workspace, "reana_job." + str(backend_job_id) + ".out"
        )
        log_files = [stderr_file, stdout_file]
        job_log = ""
        try:
            for file in log_files:
                with open(file, "r") as log_file:
                    job_log += log_file.read()
            return job_log
        except Exception as e:
            msg = "Job logs of {} were not found. {}".format(backend_job_id, e)
            logging.error(msg, exc_info=True)
            return msg
