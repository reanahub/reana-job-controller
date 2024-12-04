# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""CERN HTCondor Job Manager."""

import base64
import logging
import os
import shlex
import threading
from shutil import copyfile

import classad
from flask import current_app
from reana_db.database import Session
from reana_db.models import Workflow
from retrying import retry
from reana_commons.config import HTCONDOR_JOB_FLAVOURS

from reana_job_controller.job_manager import JobManager
from reana_job_controller.utils import initialize_krb5_token

thread_local = threading.local()


class HTCondorJobManagerCERN(JobManager):
    """CERN HTCondor job management."""

    MAX_NUM_RETRIES = 3
    """Maximum number of tries used for getting schedd, job submission and
    spooling output.
    """
    RETRY_WAIT_TIME = 10000
    """Wait time between retries in miliseconds."""

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
        htcondor_max_runtime="",
        htcondor_accounting_group=None,
        **kwargs,
    ):
        """Instantiate HTCondor job manager.

        :param docker_img: Docker image.
        :type docker_img: str
        :param cmd: Command to execute.
        :type cmd: list
        :param prettified_cmd: pretified version of command to execute.
        :type prettified_cmd: str
        :param env_vars: Environment variables.
        :type env_vars: dict
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
        :unpacked_img: if unpacked_img should be used
        :type unpacked_img: bool
        :param htcondor_max_runtime: Maximum runtime of a HTCondor job.
        :type htcondor_max_runtime: str
        :param htcondor_accounting_group: Accounting group of a HTCondor job.
        :type htcondor_accounting_group: str
        """
        super(HTCondorJobManagerCERN, self).__init__(
            docker_img=docker_img,
            cmd=cmd,
            prettified_cmd=prettified_cmd,
            env_vars=env_vars,
            workflow_uuid=workflow_uuid,
            workflow_workspace=workflow_workspace,
            job_name=job_name,
        )
        self.compute_backend = "HTCondor"
        self.cvmfs_mounts = cvmfs_mounts
        self.shared_file_system = shared_file_system
        self.workflow = self._get_workflow()
        self.unpacked_img = unpacked_img
        self.htcondor_max_runtime = htcondor_max_runtime
        self.htcondor_accounting_group = htcondor_accounting_group

        # We need to import the htcondor package later during runtime after the Kerberos environment is fully initialised.
        # Without a valid Kerberos ticket, importing will exit with "ERROR: Unauthorized 401 - do you have authentication tokens? Error "/usr/bin/myschedd.sh |"
        initialize_krb5_token(workflow_uuid=self.workflow_uuid)
        globals()["htcondor"] = __import__("htcondor")

    @JobManager.execution_hook
    def execute(self):
        """Execute / submit a job with HTCondor."""
        os.chdir(self.workflow_workspace)
        job_ad = classad.ClassAd()
        job_ad["JobDescription"] = (
            self.workflow.get_full_workflow_name() + "_" + self.job_name
        )
        job_ad["JobMaxRetries"] = 3
        job_ad["LeaveJobInQueue"] = classad.ExprTree(
            "(JobStatus == 4) && ((StageOutFinish =?= UNDEFINED) || "
            "(StageOutFinish == 0))"
        )
        job_ad["Cmd"] = (
            "./job_wrapper.sh"
            if not self.unpacked_img
            else "./job_singularity_wrapper.sh"
        )
        if not self.unpacked_img:
            job_ad["Arguments"] = self._format_arguments()
            job_ad["DockerImage"] = self.docker_img
            job_ad["WantDocker"] = True
            job_ad["DockerNetworkType"] = "host"
        job_ad["Environment"] = self._format_env_vars()
        job_ad["Out"] = classad.ExprTree(
            'strcat("reana_job.", ClusterId, ".", ProcId, ".out")'
        )
        job_ad["Err"] = classad.ExprTree(
            'strcat("reana_job.", ClusterId, ".", ProcId, ".err")'
        )
        job_ad["log"] = classad.ExprTree('strcat("reana_job.", ClusterId, ".err")')
        job_ad["ShouldTransferFiles"] = "YES"
        job_ad["WhenToTransferOutput"] = "ON_EXIT"
        job_ad["TransferInput"] = self._get_input_files()
        job_ad["TransferOutput"] = "."
        job_ad["PeriodicRelease"] = classad.ExprTree("(HoldReasonCode == 35)")
        if self.htcondor_max_runtime in HTCONDOR_JOB_FLAVOURS.keys():
            job_ad["JobFlavour"] = self.htcondor_max_runtime
        elif str.isdigit(self.htcondor_max_runtime):
            job_ad["MaxRunTime"] = int(self.htcondor_max_runtime)
        else:
            job_ad["MaxRunTime"] = 3600
        if self.htcondor_accounting_group:
            job_ad["AccountingGroup"] = self.htcondor_accounting_group
        future = current_app.htcondor_executor.submit(self._submit, job_ad)
        clusterid = future.result()
        return clusterid

    def _replace_absolute_paths_with_relative(self, cmd):
        """Replace absolute with relative path."""
        relative_paths_command = None
        if self.workflow_workspace in cmd:
            relative_paths_command = cmd.replace(self.workflow_workspace + "/", "")
        return relative_paths_command

    def _format_arguments(self):
        """Format HTCondor job execution arguments."""
        if self.workflow.type_ in ["serial", "snakemake"]:
            # Take only the user's command, removes the change directory to workflow workspace
            # added by RWE-Serial/Snakemake since HTCondor implementation does not need it.
            # E.g. "cd /path/to/workspace ; user-command" -> "user-command"
            base_cmd = self.cmd.split(maxsplit=3)[3]
            if self.workflow.type_ == "snakemake":
                # For Snakemake workflows, also remove the workspace path from
                # `jobfinished` and `jobfailed` touch commands.
                base_cmd = base_cmd.replace(
                    os.path.join(self.workflow_workspace, ""), ""
                )
        elif self.workflow.type_ == "cwl":
            base_cmd = self.cmd.replace(self.workflow_workspace, "$_CONDOR_JOB_IWD")
        elif self.workflow.type_ == "yadage":
            if "base64" in self.cmd:
                # E.g. echo ZWNobyAxCg==|base64 -d|bash
                base_64_encoded_cmd = self.cmd.split("|")[0].split()[1]
                decoded_cmd = base64.b64decode(base_64_encoded_cmd).decode("utf-8")
                base_cmd = (
                    self._replace_absolute_paths_with_relative(decoded_cmd)
                    or decoded_cmd
                )
            else:
                if self.workflow_workspace in self.cmd:
                    base_cmd = (
                        self._replace_absolute_paths_with_relative(self.cmd) or self.cmd
                    )
        return "echo {}|base64 -d".format(
            base64.b64encode(base_cmd.encode("utf-8")).decode("utf-8")
        )

    def _format_env_vars(self):
        """Return job env vars in job description format."""
        job_env = ""
        for key, value in self.env_vars.items():
            job_env += " {0}={1}".format(key, value)
        return job_env

    def _get_workflow(self):
        """Get workflow from db."""
        workflow = (
            Session.query(Workflow).filter_by(id_=self.workflow_uuid).one_or_none()
        )
        if workflow:
            return workflow
        else:
            pass

    def _get_input_files(self):
        """Get files and dirs from workflow space."""
        input_files = []
        self._copy_wrapper_file()
        forbidden_files = [".job.ad", ".machine.ad", ".chirp.config"]
        skip_extensions = (".err", ".log", ".out")
        for item in os.listdir(self.workflow_workspace):
            if item not in forbidden_files and not item.endswith(skip_extensions):
                input_files.append(item)

        return ",".join(input_files)

    def _copy_wrapper_file(self):
        """Copy job wrapper file to workspace."""
        try:
            if not self.unpacked_img:
                copyfile(
                    "/etc/job_wrapper.sh",
                    os.path.join(self.workflow_workspace + "/" + "job_wrapper.sh"),
                )
            else:
                template = (
                    "#!/bin/bash \n"
                    "singularity exec "
                    "--home $PWD:/srv "
                    "--bind $PWD:/srv "
                    "--bind /cvmfs "
                    "--bind /eos "
                    "{DOCKER_IMG} "
                    "bash -c {CMD}".format(
                        DOCKER_IMG=self.docker_img,
                        CMD=shlex.quote(self._format_arguments() + " | bash"),
                    )
                )
                f = open("job_singularity_wrapper.sh", "w")
                f.write(template)
                f.close()
        except Exception as e:
            logging.error(
                "Failed to copy job wrapper file: {0}".format(e), exc_info=True
            )
            raise e

    @retry(stop_max_attempt_number=MAX_NUM_RETRIES, wait_fixed=RETRY_WAIT_TIME)
    def _submit(self, job_ad):
        """Execute submission transaction."""
        ads = []
        schedd = HTCondorJobManagerCERN._get_schedd()
        logging.info("Submiting job - {}".format(job_ad))
        clusterid = schedd.submit(job_ad, 1, True, ads)
        HTCondorJobManagerCERN._spool_input(ads)
        return clusterid

    @retry(stop_max_attempt_number=MAX_NUM_RETRIES, wait_fixed=RETRY_WAIT_TIME)
    def _spool_input(ads):
        schedd = HTCondorJobManagerCERN._get_schedd()
        logging.info("Spooling job inputs - {}".format(ads))
        schedd.spool(ads)

    @retry(stop_max_attempt_number=MAX_NUM_RETRIES, wait_fixed=RETRY_WAIT_TIME)
    def _get_schedd():
        """Find and return the HTCondor schedd."""
        schedd = getattr(thread_local, "MONITOR_THREAD_SCHEDD", None)
        if schedd is None:
            setattr(
                thread_local, "MONITOR_THREAD_SCHEDD", htcondor.Schedd()  # noqa: F821
            )
        logging.info("Getting schedd: {}".format(thread_local.MONITOR_THREAD_SCHEDD))
        return thread_local.MONITOR_THREAD_SCHEDD

    def stop(backend_job_id):
        """Stop HTCondor job execution."""
        try:
            schedd = HTCondorJobManagerCERN._get_schedd()
            schedd.act(
                htcondor.JobAction.Remove,  # noqa: F821
                "ClusterId=={}".format(backend_job_id),
            )
        except Exception as e:
            logging.error(e, exc_info=True)

    @retry(stop_max_attempt_number=MAX_NUM_RETRIES, wait_fixed=RETRY_WAIT_TIME)
    def spool_output(backend_job_id):
        """Transfer job output."""
        schedd = HTCondorJobManagerCERN._get_schedd()
        logging.info("Spooling jobs {} output.".format(backend_job_id))
        schedd.retrieve("ClusterId == {}".format(backend_job_id))

    @classmethod
    def get_logs(cls, backend_job_id, **kwargs):
        """Return job logs if log files are present.

        :param backend_job_id: ID of the job in the backend.
        :param kwargs: Additional parameters needed to fetch logs.
            In the case of HTCondor, the ``workspace`` parameter is needed.
        :return: String containing the job logs.
        """
        if "workspace" not in kwargs:
            raise ValueError("Missing 'workspace' parameter")
        workspace = kwargs["workspace"]

        stderr_file = os.path.join(
            workspace, "reana_job." + str(backend_job_id) + ".0.err"
        )
        stdout_file = os.path.join(
            workspace, "reana_job." + str(backend_job_id) + ".0.out"
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

    def find_job_in_history(backend_job_id):
        """Return job if present in condor history."""
        schedd = HTCondorJobManagerCERN._get_schedd()
        ads = ["ClusterId", "JobStatus", "ExitCode", "RemoveReason"]
        condor_it = schedd.history(
            "ClusterId == {0}".format(backend_job_id), ads, match=1
        )
        try:
            condor_job = next(condor_it)
            return condor_job
        except Exception:
            # Did not match to any job in the history  yet
            return None
