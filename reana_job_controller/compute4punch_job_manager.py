import base64
import logging
import os
import re

from paramiko.sftp_client import SFTPClient
from stat import S_ISDIR
from typing import Iterable

from reana_commons.workspace import is_directory, open_file, walk
from reana_job_controller.job_manager import JobManager
from reana_job_controller.utils import SSHClient, motley_cue_auth_strategy_factory
from reana_job_controller.config import (
    C4P_LOGIN_NODE_HOSTNAME,
    C4P_LOGIN_NODE_PORT,
    C4P_SSH_TIMEOUT,
    C4P_SSH_BANNER_TIMEOUT,
    C4P_SSH_AUTH_TIMEOUT,
)


class Compute4PUNCHJobManager(JobManager):
    """Compute4PUNCH Job Manager"""

    C4P_WORKSPACE_PATH = ""
    """Absolute path on the Compute4PUNCH head node used for submission"""
    C4P_HOME_PATH = ""
    """Default Compute4PUNCH home directory"""
    SUBMIT_ID_PATTERN = re.compile(r"Proc\s(\d+\.\d+)")
    """ regex to search the Job ID in a submit Proc line """

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
        c4p_cpu_cores=None,
        c4p_memory_limit=None,
        c4p_additional_requirements=None,
    ):
        """
        Compute4PUNCH Job Manager.

        :param docker_img: Docker image.
        :type docker_img: str
        :param cmd: Command to execute.
        :type cmd: list
        :param prettified_cmd: prettified version of command to execute.
        :type prettified_cmd: str
        :param env_vars: Environment variables.
        :type env_vars: dict
        :param workflow_uuid: Unique workflow id.
        :type workflow_uuid: str
        :type workflow_workspace: str
        :param cvmfs_mounts: list of CVMFS mounts as a string.
        :type cvmfs_mounts: str
        :param shared_file_system: if shared file system is available.
        :type shared_file_system: bool
        :param job_name: Name of the job
        :type job_name: str
        :param c4p_cpu_cores: number of CPU cores to use on C4P
        :type c4p_cpu_cores: int, str
        :param c4p_memory_limit: maximum memory to be used on C4P
        :type c4p_memory_limit: int, str
        :param c4p_additional_requirements: additional HTCondor requirements for the job
        :type c4p_additional_requirements: str
        """
        super(Compute4PUNCHJobManager, self).__init__(
            docker_img=docker_img,
            cmd=cmd,
            prettified_cmd=prettified_cmd,
            env_vars=env_vars,
            workflow_uuid=workflow_uuid,
            workflow_workspace=workflow_workspace,
            job_name=job_name,
        )
        self.c4p_connection = SSHClient(
            hostname=C4P_LOGIN_NODE_HOSTNAME,
            port=C4P_LOGIN_NODE_PORT,
            timeout=C4P_SSH_TIMEOUT,
            banner_timeout=C4P_SSH_BANNER_TIMEOUT,
            auth_timeout=C4P_SSH_AUTH_TIMEOUT,
            auth_strategy=motley_cue_auth_strategy_factory(
                hostname=C4P_LOGIN_NODE_HOSTNAME
            ),
        )
        self.compute_backend = "compute4punch"
        self.cvmfs_mounts = cvmfs_mounts
        self.shared_file_system = shared_file_system
        self.job_execution_script_path = os.path.join(
            self.c4p_abs_workspace_path, "run.sh"
        )
        self.job_description_path = os.path.join(
            self.c4p_abs_workspace_path, "submit.jdl"
        )

        self.c4p_cpu_cores = c4p_cpu_cores or 8
        self.c4p_memory_limit = c4p_memory_limit or 20000
        self.c4p_additional_requirements = c4p_additional_requirements

        self._workflow = None

    @JobManager.execution_hook
    def execute(self) -> str:
        """
        Execute/submit a job on Compute4PUNCH.

        :return: Backend Job ID
        """
        self._create_c4p_workspace_environment()
        self._create_c4p_job_execution_script()
        self._create_c4p_job_description()
        self._upload_job_inputs()

        submit_cmd_list = [
            f"cd {self.c4p_abs_workspace_path}",
            f"condor_submit --verbose {os.path.basename(self.job_description_path)}",
        ]

        response = self.c4p_connection.exec_command("&&".join(submit_cmd_list))

        return next(
            self.SUBMIT_ID_PATTERN.search(line).group(1)
            for line in response.splitlines()
            if line.startswith("** Proc")
        )

    @classmethod
    def get_logs(cls, backend_job_id: str, **kwargs) -> str:
        """
        Return job logs if log files are present.

        :param backend_job_id: ID of the job in the backend.
        :param kwargs: Additional parameters needed to fetch logs.
            In the case of Slurm, the ``workspace`` parameter is needed.
        :return: String containing the job logs.
        """
        if "workspace" not in kwargs:
            raise ValueError("Missing 'workspace' parameter")
        workspace = kwargs["workspace"]

        job_log = ""

        try:
            for log in ("out", "err"):
                filepath = f"logs/{backend_job_id}.{log}"
                with open_file(workspace, filepath) as f:
                    job_log += f.read()
            return job_log
        except FileNotFoundError as e:
            msg = f"Job logs of {backend_job_id} were not found. {e}"
            logging.error(msg, exc_info=True)
            return msg

    def get_outputs(self) -> None:
        """
        Transfer job outputs from Compute4PUNCH to local REANA workspace.
        """
        sftp_client = self.c4p_connection.ssh_client.open_sftp()
        sftp_client.chdir(self.c4p_abs_workspace_path)
        try:
            self._download_output_directory(
                sftp_client, self.c4p_abs_workspace_path, self.workflow_workspace
            )
        finally:
            sftp_client.close()

    def stop(self, backend_job_id: str) -> None:
        """
        Stop job execution.

        :param backend_job_id: The backend job id
        :type backend_job_id: str
        """
        try:
            self.c4p_connection.exec_command(f"condor_rm {backend_job_id}")
        except Exception as ex:
            logging.error(ex, exc_info=True)

    @property
    def c4p_home_path(self) -> str:
        """
        Determine and return the Compute4PUNCH home directory on Compute4PUNCH
        """
        if not self.C4P_HOME_PATH:
            self.C4P_HOME_PATH = self.c4p_connection.exec_command("pwd").strip()
        return self.C4P_HOME_PATH

    @property
    def c4p_abs_workspace_path(self) -> str:
        """
        Determine and return the absolute Compute4PUNCH workspace path
        """
        if not self.C4P_WORKSPACE_PATH:
            self.C4P_WORKSPACE_PATH = os.path.join(
                self.c4p_home_path, self.c4p_rel_workspace_path
            )
        return self.C4P_WORKSPACE_PATH

    @property
    def c4p_rel_workspace_path(self) -> str:
        """
        Determine and return the relative Compute4PUNCH workspace path
        """
        return os.path.join(self.workflow_workspace, self.workflow_uuid)

    def _create_c4p_job_description(self) -> None:
        """
        Create job description for Compute4PUNCH
        """
        job_inputs = ",".join(self._get_inputs())
        job_outputs = "."  # download everything from remote job
        job_description_template = [
            f"executable = {os.path.basename(self.job_execution_script_path)}",
            "output = logs/$(cluster).$(process).out",
            "error = logs/$(cluster).$(process).err",
            "log = cluster.log",
            "ShouldTransferFiles = YES",
            "WhenToTransferOutput = ON_SUCCESS",
            f"transfer_input_files = {job_inputs}" if job_inputs else "",
            f"transfer_output_files = {job_outputs}",
            f"request_cpus = {self.c4p_cpu_cores}",
            f"request_memory = {self.c4p_memory_limit}",
            f'+SINGULARITY_JOB_CONTAINER = "{self.docker_img}"',
            (
                f"requirements = {self.c4p_additional_requirements}"
                if self.c4p_additional_requirements
                else ""
            ),
            "queue 1",
        ]
        job_description = "\n".join(filter(None, job_description_template))

        self.c4p_connection.exec_command(
            f"cat <<< '{job_description}' > {self.job_description_path}"
        )

    def _create_c4p_job_execution_script(self) -> None:
        """
        Create job execution script for Compute4PUNCH
        """
        self.cmd = self._encode_cmd(self.cmd)
        job_execution_script_template = ["#!/bin/bash", f"{self.cmd}"]
        job_execution_script = "\n".join(job_execution_script_template)

        self.c4p_connection.exec_command(
            f"cat <<< '{job_execution_script}' > {self.job_execution_script_path} && "
            f"chmod +x {self.job_execution_script_path}"
        )

    def _create_c4p_workspace_environment(self) -> None:
        """
        Create workspace environment for REANA @ Compute4PUNCH
        """
        self.c4p_connection.exec_command(f"mkdir -p {self.c4p_abs_workspace_path}")
        self.c4p_connection.exec_command(
            os.path.join(
                f"mkdir -p {os.path.join(self.c4p_abs_workspace_path, 'logs')}"
            )
        )

    def _download_output_directory(
        self, sftp_client: SFTPClient, remote_dir: str, local_dir: str
    ) -> None:
        """
        Download output directory and content to a local directory.

        :param sftp_client: SFTP client to use for downloading
        :type sftp_client: SFTPClient
        :param remote_dir: Remote directory to download
        :type remote_dir: str
        :param local_dir: Local destination directory
        :type local_dir: str
        """
        skipped_output_files = (
            "cluster.log",
            "_condor_stdout",
            "_condor_stderr",
            "run.sh",
            "submit.jdl",
            "tmp",
            "var_tmp",
        )  # skip intermediate and temporary htcondor files
        os.path.exists(local_dir) or os.makedirs(local_dir)
        for item in filter(
            lambda x: x.filename not in skipped_output_files,
            sftp_client.listdir_attr(remote_dir),
        ):
            remote_path = os.path.join(remote_dir, item.filename)
            local_path = os.path.join(local_dir, item.filename)
            if S_ISDIR(item.st_mode):
                self._download_output_directory(sftp_client, remote_path, local_path)
            else:
                print(f"Download {remote_path} to {local_path}")
                sftp_client.get(remote_path, local_path)

    @staticmethod
    def _encode_cmd(cmd: str) -> str:
        """
        Encode base64 cmd.

        :param cmd: Command to encode
        :type cmd: str
        """
        encoded_cmd = base64.b64encode(cmd.encode("utf-8")).decode("utf-8")
        return f"echo {encoded_cmd} | base64 -d | bash"

    def _get_inputs(self) -> Iterable:
        """
        Collect all input files in the local REANA workspace.
        """
        skipped_input_files = (".job.ad", ".machine.ad", ".chirp.config")
        return filter(
            lambda x: x not in skipped_input_files,
            walk(
                workspace=self.workflow_workspace,
            ),
        )

    def _upload_job_inputs(self) -> None:
        """
        Upload job inputs to Compute4PUNCH
        """
        sftp_client = self.c4p_connection.ssh_client.open_sftp()
        sftp_client.chdir(self.c4p_rel_workspace_path)

        try:
            for job_input in self._get_inputs():
                if is_directory(self.workflow_workspace, job_input):
                    try:  # check if directory already exists
                        sftp_client.stat(job_input)
                    except FileNotFoundError:
                        sftp_client.mkdir(job_input)
                    finally:
                        continue
                else:
                    local_path = os.path.join(self.workflow_workspace, job_input)
                    remote_path = os.path.join(self.c4p_abs_workspace_path, job_input)
                    sftp_client.put(local_path, remote_path)
        finally:
            sftp_client.close()
