# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023, 2024, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""CERN HTCondor Job Manager."""

import base64
import hashlib
import logging
import os
import shlex
import shutil
import stat
import threading
from shutil import copyfile

import classad2 as classad
from flask import current_app
from reana_db.database import Session
from reana_db.models import Workflow
from retrying import retry
from reana_commons.config import HTCONDOR_JOB_FLAVOURS

from reana_job_controller.job_manager import JobManager
from reana_job_controller.schemas import htcondor_quantity_to_unit
from reana_job_controller.utils import initialize_krb5_token

thread_local = threading.local()


class HTCondorJobManagerCERN(JobManager):
    """CERN HTCondor job management."""

    FILE_TRANSFER_DIRECTORY_PREFIX = "reana_job."
    FILE_TRANSFER_DIRECTORY_SUFFIX = ".filetransfer"
    INTERNAL_OUTPUT_FILES = {
        ".chirp.config",
        ".job.ad",
        ".machine.ad",
        "_condor_stderr",
        "_condor_stdout",
        "condor_exec.exe",
    }
    INTERNAL_WORKFLOW_PATHS = {
        "snakemake": {".snakemake"},
        "yadage": {"_yadage"},
    }

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
        secret_names=None,
        secrets=None,
        kubernetes_uid=None,
        unpacked_img=False,
        htcondor_max_runtime="",
        htcondor_accounting_group=None,
        htcondor_request_cpus="",
        htcondor_request_memory="",
        htcondor_request_disk="",
        htcondor_requirements="",
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
        :param htcondor_request_cpus: Number of CPU cores requested for the
            HTCondor job (positive integer as string).
        :type htcondor_request_cpus: str
        :param htcondor_request_memory: Memory requested for the HTCondor
            job. Accepts a positive integer with an optional
            ``K|KB|M|MB|G|GB|T|TB`` suffix (case-insensitive, binary
            multipliers). When no suffix is given, the value is interpreted
            in megabytes, the native unit of ``RequestMemory``. Examples:
            ``"4096"``, ``"4 GB"``, ``"4gb"``.
        :type htcondor_request_memory: str
        :param htcondor_request_disk: Disk requested for the HTCondor job.
            Same quantity syntax as ``htcondor_request_memory``; when no
            suffix is given, the value is interpreted in kilobytes, the
            native unit of ``RequestDisk``. Examples: ``"10000"``,
            ``"10 GB"``, ``"10tb"``.
        :type htcondor_request_disk: str
        :param htcondor_requirements: HTCondor ``Requirements`` ClassAd
            expression to select the machine(s) the job can run on. REANA
            does not compose this with any backend-provided default; the
            value is the full expression.
        :type htcondor_requirements: str
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
        self.secret_names = secret_names
        self.secrets = secrets
        self.htcondor_max_runtime = htcondor_max_runtime
        self.htcondor_accounting_group = htcondor_accounting_group
        self.htcondor_request_cpus = htcondor_request_cpus
        self.htcondor_request_memory = htcondor_request_memory
        self.htcondor_request_disk = htcondor_request_disk
        self.htcondor_requirements = htcondor_requirements
        self.file_transfer_workspace = os.path.join(
            self.workflow_workspace,
            "{0}{1}{2}".format(
                self.FILE_TRANSFER_DIRECTORY_PREFIX,
                self.job_id,
                self.FILE_TRANSFER_DIRECTORY_SUFFIX,
            ),
        )
        self.input_file_signatures = {}
        self.input_symlinks = set()

        # Import HTCondor only after initialising Kerberos. Importing the module
        # evaluates the ``myschedd.sh`` configuration, which requires a valid
        # ticket.
        kerberos_secrets = (
            self.secrets.get_scoped_secrets(self.secret_names, kerberos=True)
            if self.secrets
            else None
        )
        initialize_krb5_token(
            workflow_uuid=self.workflow_uuid,
            secrets=kerberos_secrets,
        )
        globals()["htcondor"] = __import__("htcondor2")

    @JobManager.execution_hook
    def execute(self):
        """Execute / submit a job with HTCondor."""
        os.chdir(self.workflow_workspace)
        executable_name = (
            "job_wrapper.sh" if not self.unpacked_img else "job_singularity_wrapper.sh"
        )
        transfer_input_files = self._prepare_file_transfer()
        try:
            submit_description = {
                "description": (
                    self.workflow.get_full_workflow_name() + "_" + self.job_name
                ),
                "MY.JobMaxRetries": "3",
                "leave_in_queue": (
                    "(JobStatus == 4) && ((StageOutFinish =?= UNDEFINED) || "
                    "(StageOutFinish == 0))"
                ),
                "initialdir": self.file_transfer_workspace,
                "executable": os.path.join(self.workflow_workspace, executable_name),
                "environment": self._format_env_vars(),
                "output": "reana_job.$(ClusterId).$(ProcId).out",
                "error": "reana_job.$(ClusterId).$(ProcId).err",
                "should_transfer_files": "YES",
                "when_to_transfer_output": "ON_EXIT",
                "transfer_input_files": transfer_input_files,
                "transfer_output_files": ".",
                "periodic_release": "(HoldReasonCode == 35)",
            }
            if not self.unpacked_img:
                submit_description["arguments"] = self._format_arguments()
                # Keep CERN's existing legacy Docker job attributes. Using the
                # ``docker_image`` submit command would implicitly migrate these
                # jobs to HTCondor's Container Universe.
                submit_description["MY.DockerImage"] = classad.quote(self.docker_img)
                submit_description["MY.WantDocker"] = "True"
                submit_description["MY.DockerNetworkType"] = classad.quote("host")
            if self.htcondor_max_runtime in HTCONDOR_JOB_FLAVOURS.keys():
                submit_description["MY.JobFlavour"] = classad.quote(
                    self.htcondor_max_runtime
                )
            elif str.isdigit(self.htcondor_max_runtime):
                submit_description["MY.MaxRunTime"] = self.htcondor_max_runtime
            else:
                submit_description["MY.MaxRunTime"] = "3600"
            if self.htcondor_accounting_group:
                submit_description["MY.AccountingGroup"] = classad.quote(
                    self.htcondor_accounting_group
                )
            if self.htcondor_request_cpus:
                submit_description["request_cpus"] = self.htcondor_request_cpus
            if self.htcondor_request_memory:
                submit_description["request_memory"] = str(
                    htcondor_quantity_to_unit(self.htcondor_request_memory, "M")
                )
            if self.htcondor_request_disk:
                submit_description["request_disk"] = str(
                    htcondor_quantity_to_unit(self.htcondor_request_disk, "K")
                )
            if self.htcondor_requirements:
                # ``MY.Requirements`` preserves the existing behaviour where the
                # supplied expression is the complete Requirements expression.
                submit_description["MY.Requirements"] = self.htcondor_requirements
            else:
                # Prevent the submit engine from generating constraints for the
                # submit host's architecture and operating system. The legacy
                # raw-ClassAd submission did not add a Requirements expression.
                submit_description["MY.Requirements"] = "True"
            self._validate_submit_description(submit_description)
            submit = htcondor.Submit(submit_description)  # noqa: F821
            future = current_app.htcondor_executor.submit(self._submit, submit)
            return future.result()
        except Exception:
            self.cleanup_file_transfer()
            raise

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
        """Return job env vars in HTCondor's new environment syntax."""
        entries = []
        for key, value in self.env_vars.items():
            entry = "{0}={1}".format(key, value)
            entry = entry.replace('"', '""').replace("'", "''")
            entries.append("'{0}'".format(entry))
        return '"{0}"'.format(" ".join(entries))

    @staticmethod
    def _validate_submit_description(submit_description):
        """Reject values that could inject additional submit commands."""
        forbidden_characters = ("\n", "\r", "\x00")
        for command, value in submit_description.items():
            if any(character in value for character in forbidden_characters):
                raise ValueError(
                    "HTCondor submit command {!r} contains a line break or "
                    "null byte".format(command)
                )

    def _get_workflow(self):
        """Get workflow from db."""
        workflow = (
            Session.query(Workflow).filter_by(id_=self.workflow_uuid).one_or_none()
        )
        if workflow:
            return workflow
        else:
            pass

    @classmethod
    def _is_file_transfer_directory(cls, name):
        """Return whether a workspace entry is an HTCondor transfer directory."""
        return name.startswith(cls.FILE_TRANSFER_DIRECTORY_PREFIX) and name.endswith(
            cls.FILE_TRANSFER_DIRECTORY_SUFFIX
        )

    def _is_internal_workflow_path(self, relative_path):
        """Return whether a path contains workflow-engine runtime state."""
        workflow_type = getattr(self.workflow, "type_", None)
        internal_paths = self.INTERNAL_WORKFLOW_PATHS.get(workflow_type, set())
        top_level_path = relative_path.split(os.sep, 1)[0]
        return top_level_path in internal_paths

    def _exclude_internal_workflow_paths(self, root, entries, base_path):
        """Return entries excluding workflow-engine runtime state paths."""
        return [
            entry
            for entry in entries
            if not self._is_internal_workflow_path(
                os.path.relpath(os.path.join(root, entry), base_path)
            )
        ]

    @staticmethod
    def _hash_file(path):
        """Return the SHA-256 digest of a file."""
        digest = hashlib.sha256()
        with open(path, "rb") as file_object:
            for chunk in iter(lambda: file_object.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _file_signature(path):
        """Return metadata that identifies a local workspace file."""
        file_stat = os.stat(path, follow_symlinks=False)
        return (
            file_stat.st_dev,
            file_stat.st_ino,
            stat.S_IFMT(file_stat.st_mode),
            file_stat.st_size,
            file_stat.st_mtime_ns,
            file_stat.st_ctime_ns,
        )

    @classmethod
    def _files_equal(cls, first_path, second_path):
        """Return whether two regular files have identical contents."""
        if os.path.getsize(first_path) != os.path.getsize(second_path):
            return False
        return cls._hash_file(first_path) == cls._hash_file(second_path)

    def _snapshot_workspace(self):
        """Record workspace metadata before the HTCondor job runs."""
        file_signatures = {}
        symlinks = set()
        for root, directories, files in os.walk(self.workflow_workspace):
            directories[:] = self._exclude_internal_workflow_paths(
                root, directories, self.workflow_workspace
            )
            files = self._exclude_internal_workflow_paths(
                root, files, self.workflow_workspace
            )
            regular_directories = []
            for directory in directories:
                if self._is_file_transfer_directory(directory):
                    continue
                path = os.path.join(root, directory)
                relative_path = os.path.relpath(path, self.workflow_workspace)
                if os.path.islink(path):
                    symlinks.add(relative_path)
                else:
                    regular_directories.append(directory)
            directories[:] = regular_directories

            for filename in files:
                path = os.path.join(root, filename)
                relative_path = os.path.relpath(path, self.workflow_workspace)
                if os.path.islink(path):
                    symlinks.add(relative_path)
                    continue
                try:
                    file_signatures[relative_path] = self._file_signature(path)
                except FileNotFoundError:
                    # A concurrently removed file cannot be an input to this job.
                    continue
        return file_signatures, symlinks

    def _prepare_file_transfer(self):
        """Prepare an empty local destination for the returned sandbox."""
        input_files = self._get_input_files().split(",")
        input_files = [filename for filename in input_files if filename]
        self.input_file_signatures, self.input_symlinks = self._snapshot_workspace()
        os.makedirs(self.file_transfer_workspace)
        return ",".join(
            os.path.join(self.workflow_workspace, filename) for filename in input_files
        )

    def cleanup_file_transfer(self):
        """Remove the local HTCondor file-transfer workspace."""
        try:
            shutil.rmtree(self.file_transfer_workspace)
        except FileNotFoundError:
            pass
        except OSError:
            logging.error(
                "Failed to remove HTCondor file-transfer directory %s",
                self.file_transfer_workspace,
                exc_info=True,
            )

    def _validate_promotion_path(self, path):
        """Ensure that an output destination remains inside the workspace."""
        workspace = os.path.realpath(self.workflow_workspace)
        parent = os.path.realpath(os.path.dirname(path))
        if os.path.commonpath([workspace, parent]) != workspace:
            raise RuntimeError(
                "HTCondor output path escapes the workflow workspace: {}".format(path)
            )

    def _was_input_symlink(self, relative_path):
        """Return whether a path is or descends from an input symlink."""
        path_parts = relative_path.split(os.sep)
        return any(
            os.path.join(*path_parts[:part_count]) in self.input_symlinks
            for part_count in range(1, len(path_parts) + 1)
        )

    def _verify_unchanged_input_symlink(self, relative_path, returned_path):
        """Reject changed content returned for an input file symlink."""
        destination = os.path.join(self.workflow_workspace, relative_path)
        if not os.path.islink(destination) or not os.path.isfile(destination):
            self._raise_concurrent_modification(relative_path)
        try:
            files_equal = self._files_equal(returned_path, destination)
        except OSError:
            files_equal = False
        if not files_equal:
            self._raise_concurrent_modification(relative_path)

    @staticmethod
    def _raise_concurrent_modification(relative_path):
        """Raise an output conflict for a locally changed workspace path."""
        raise RuntimeError(
            "HTCondor output conflicts with a concurrently modified "
            "workspace file: {}".format(relative_path)
        )

    def promote_output(self):
        """Move new and modified HTCondor output files into the workspace."""
        if not os.path.isdir(self.file_transfer_workspace):
            raise RuntimeError(
                "HTCondor file-transfer directory does not exist: {}".format(
                    self.file_transfer_workspace
                )
            )

        for root, directories, files in os.walk(self.file_transfer_workspace):
            directories[:] = self._exclude_internal_workflow_paths(
                root, directories, self.file_transfer_workspace
            )
            files = self._exclude_internal_workflow_paths(
                root, files, self.file_transfer_workspace
            )
            for directory in list(directories):
                source = os.path.join(root, directory)
                relative_path = os.path.relpath(source, self.file_transfer_workspace)
                if self._was_input_symlink(relative_path):
                    logging.warning(
                        "Skipping returned HTCondor content rooted at input "
                        "directory symlink: %s",
                        relative_path,
                    )
                    directories.remove(directory)
                    continue
                if os.path.islink(source):
                    raise RuntimeError(
                        "Refusing to promote HTCondor output symlink: {}".format(source)
                    )

                destination = os.path.join(self.workflow_workspace, relative_path)
                self._validate_promotion_path(destination)
                if os.path.islink(destination):
                    self._raise_concurrent_modification(relative_path)
                os.makedirs(destination, exist_ok=True)

            for filename in files:
                source = os.path.join(root, filename)
                if os.path.islink(source):
                    raise RuntimeError(
                        "Refusing to promote HTCondor output symlink: {}".format(source)
                    )

                relative_path = os.path.relpath(source, self.file_transfer_workspace)
                if relative_path in self.INTERNAL_OUTPUT_FILES:
                    continue
                if self._was_input_symlink(relative_path):
                    self._verify_unchanged_input_symlink(relative_path, source)
                    continue

                destination = os.path.join(self.workflow_workspace, relative_path)
                self._validate_promotion_path(destination)
                input_signature = self.input_file_signatures.get(relative_path)
                destination_exists = os.path.lexists(destination)

                if input_signature is not None:
                    if not destination_exists or os.path.islink(destination):
                        self._raise_concurrent_modification(relative_path)
                    if self._file_signature(destination) != input_signature:
                        if os.path.isfile(destination) and self._files_equal(
                            source, destination
                        ):
                            continue
                        self._raise_concurrent_modification(relative_path)
                    if self._files_equal(source, destination):
                        continue
                elif destination_exists:
                    if (
                        not os.path.islink(destination)
                        and os.path.isfile(destination)
                        and self._files_equal(source, destination)
                    ):
                        continue
                    self._raise_concurrent_modification(relative_path)

                os.makedirs(os.path.dirname(destination), exist_ok=True)
                os.replace(source, destination)

        self.cleanup_file_transfer()

    def _get_input_files(self):
        """Get files and dirs from workflow space."""
        input_files = []
        self._copy_wrapper_file()
        forbidden_files = [".job.ad", ".machine.ad", ".chirp.config"]
        skip_extensions = (".err", ".log", ".out")
        for item in os.listdir(self.workflow_workspace):
            if (
                item not in forbidden_files
                and not item.endswith(skip_extensions)
                and not self._is_file_transfer_directory(item)
                and not self._is_internal_workflow_path(item)
            ):
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
    def _submit(self, submit):
        """Execute submission transaction."""
        schedd = HTCondorJobManagerCERN._get_schedd()
        logging.info("Submitting job - {}".format(submit))
        result = schedd.submit(submit, count=1, spool=True)
        HTCondorJobManagerCERN._spool_input(result)
        return result.cluster()

    @staticmethod
    @retry(stop_max_attempt_number=MAX_NUM_RETRIES, wait_fixed=RETRY_WAIT_TIME)
    def _spool_input(result):
        schedd = HTCondorJobManagerCERN._get_schedd()
        logging.info("Spooling job inputs - {}".format(result))
        schedd.spool(result)

    @staticmethod
    @retry(stop_max_attempt_number=MAX_NUM_RETRIES, wait_fixed=RETRY_WAIT_TIME)
    def _get_schedd():
        """Find and return the HTCondor schedd."""
        schedd = getattr(thread_local, "MONITOR_THREAD_SCHEDD", None)
        if schedd is None:
            schedd_host = htcondor.param.get("SCHEDD_HOST")  # noqa: F821
            if not schedd_host:
                raise RuntimeError("SCHEDD_HOST is not configured")

            schedd_location = htcondor.Collector().locate(  # noqa: F821
                htcondor.DaemonType.Schedd, schedd_host  # noqa: F821
            )
            if schedd_location is None:
                raise RuntimeError(
                    "Unable to locate HTCondor schedd {}".format(schedd_host)
                )

            schedd = htcondor.Schedd(schedd_location)  # noqa: F821
            setattr(thread_local, "MONITOR_THREAD_SCHEDD", schedd)
        logging.info("Getting schedd: {}".format(thread_local.MONITOR_THREAD_SCHEDD))
        return thread_local.MONITOR_THREAD_SCHEDD

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    def find_job_in_history(backend_job_id):
        """Return job if present in condor history."""
        schedd = HTCondorJobManagerCERN._get_schedd()
        ads = ["ClusterId", "JobStatus", "ExitCode", "RemoveReason"]
        condor_jobs = schedd.history(
            "ClusterId == {0}".format(backend_job_id), ads, match=1
        )
        return condor_jobs[0] if condor_jobs else None
