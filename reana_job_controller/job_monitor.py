# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job monitoring wrapper."""

import logging
import threading
import time
import traceback
from typing import Optional, Dict

from kubernetes import client, watch
from reana_commons.config import REANA_RUNTIME_KUBERNETES_NAMESPACE
from reana_commons.k8s.api_client import current_k8s_corev1_api_client
from reana_db.models import JobStatus

from reana_job_controller.config import (
    COMPUTE_BACKENDS,
    SLURM_HEADNODE_HOSTNAME,
    SLURM_HEADNODE_PORT,
    SLURM_SSH_TIMEOUT,
    SLURM_SSH_BANNER_TIMEOUT,
    SLURM_SSH_AUTH_TIMEOUT,
    C4P_LOGIN_NODE_HOSTNAME,
    C4P_LOGIN_NODE_PORT,
    C4P_SSH_TIMEOUT,
    C4P_SSH_BANNER_TIMEOUT,
    C4P_SSH_AUTH_TIMEOUT,
    KUEUE_ENABLED,
    KUEUE_DEFAULT_QUEUE,
)

from reana_job_controller.job_db import JOB_DB, store_job_logs, update_job_status
from reana_job_controller.utils import (
    SSHClient,
    singleton,
    csv_parser,
    motley_cue_auth_strategy_factory,
)


class JobMonitor:
    """Job monitor interface."""

    def __init__(self, thread_name: str, app=None):
        """Initialize REANA job monitors."""
        self.job_event_reader_thread = threading.Thread(
            name=thread_name, target=self.watch_jobs, args=(JOB_DB, app)
        )
        self.job_event_reader_thread.daemon = True
        self.job_event_reader_thread.start()
        self.job_db = JOB_DB

    def watch_jobs(self, job_db, app):
        """Monitor running jobs."""
        raise NotImplementedError


@singleton
class JobMonitorKubernetes(JobMonitor):
    """Kubernetes job monitor."""

    def __init__(self, workflow_uuid: Optional[str] = None, **kwargs):
        """Initialize Kubernetes job monitor thread."""
        self.job_manager_cls = COMPUTE_BACKENDS["kubernetes"]()
        self.workflow_uuid = workflow_uuid
        super(__class__, self).__init__(thread_name="kubernetes_job_monitor")

    def _get_remaining_jobs(
        self, compute_backend="kubernetes", statuses_to_skip=None
    ) -> Dict[str, str]:
        """Get remaining jobs according to a set of conditions.

        :param compute_backend: For which compute backend to search remaining
            jobs.
        :param statuses_to_skip: List of statuses to skip when searching for
            remaining jobs.
        :type compute_backend: str
        :type statuses_to_skip: list

        :return: Dictionary composed of backend IDs as keys and REANA job IDs
            as value.
        :rtype: dict
        """
        remaining_jobs = dict()
        statuses_to_skip = statuses_to_skip or []
        for job_id, job_dict in self.job_db.items():
            is_remaining = (
                not self.job_db[job_id]["deleted"]
                and self.job_db[job_id]["compute_backend"] == compute_backend
                and not self.job_db[job_id]["status"] in statuses_to_skip
            )
            if is_remaining:
                remaining_jobs[job_dict["backend_job_id"]] = job_id
        return remaining_jobs

    def get_reana_job_id(self, backend_job_id: str) -> str:
        """Get REANA job ID."""
        remaining_jobs = self._get_remaining_jobs()
        return remaining_jobs[backend_job_id]

    @staticmethod
    def get_backend_job_id(job_pod):
        """Get the backend job id for the backend object.

        :param job_pod: Compute backend job object (Kubernetes V1Pod
            https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1Pod.md)

        :return: Backend job ID.
        :rtype: str
        """
        return job_pod.metadata.labels["job-name"]

    def should_process_job_pod(self, job_pod) -> bool:
        """Decide whether the job should be processed or not.

        Each job is processed only once, when it reaches a final state (either `failed` or `finished`).

        :param job_pod: Compute backend job object (Kubernetes V1Pod
            https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1Pod.md)
        """
        remaining_jobs = self._get_remaining_jobs(
            statuses_to_skip=[
                JobStatus.finished.name,
                JobStatus.failed.name,
                JobStatus.stopped.name,
            ]
        )
        backend_job_id = self.get_backend_job_id(job_pod)
        is_job_in_remaining_jobs = backend_job_id in remaining_jobs

        job_status = self.get_job_status(job_pod)
        is_job_completed = job_status in [
            JobStatus.finished.name,
            JobStatus.failed.name,
        ]

        return is_job_in_remaining_jobs and is_job_completed

    def should_process_job(self, job) -> bool:
        """Decide whether the job should be processed or not.

        Each job is processed only once, when it reaches a final state (either `failed` or `finished`).

        :param job: Compute backend job object (Kubernetes V1Job
            https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1Job.md)
        """
        remaining_jobs = self._get_remaining_jobs(
            statuses_to_skip=[
                JobStatus.finished.name,
                JobStatus.failed.name,
                JobStatus.stopped.name,
            ]
        )

        is_job_in_remaining_jobs = job.metadata.name in remaining_jobs
        is_job_completed = not job.status.active and (
            job.status.succeeded or job.status.failed
        )

        return is_job_in_remaining_jobs and is_job_completed

    @staticmethod
    def _get_job_container_statuses(job_pod):
        return (job_pod.status.container_statuses or []) + (
            job_pod.status.init_container_statuses or []
        )

    def clean_job(self, job_id):
        """Clean up the created Kubernetes Job.

        :param job_id: Kubernetes job ID.
        """
        try:
            logging.info("Cleaning Kubernetes job {} ...".format(job_id))
            self.job_manager_cls.stop(job_id)
            self.job_db[self.get_reana_job_id(job_id)]["deleted"] = True
        except client.rest.ApiException as e:
            logging.error(f"Error from Kubernetes API while cleaning up job: {e}")
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.error("Unexpected error: {}".format(e))

    def get_job_status(self, job_pod) -> Optional[str]:
        """Get Kubernetes based REANA job status."""
        status = None
        backend_job_id = self.get_backend_job_id(job_pod)
        container_statuses = self._get_job_container_statuses(job_pod)

        if job_pod.status.phase == "Succeeded":
            # checking that all the containers are `Completed`, as sometimes there
            # can be `OOMKilled` containers that are considered as successful
            for container in container_statuses:
                try:
                    reason = container.state.terminated.reason
                except AttributeError:
                    reason = None
                if not reason:
                    logging.info(
                        f"No termination reason for container {container.name} in "
                        f"Kubernetes job {backend_job_id}, assuming successful."
                    )
                elif reason != "Completed":
                    logging.warn(
                        f"Kubernetes job id: {backend_job_id} failed, phase 'Succeeded' but "
                        f"container '{container.name}' was terminated because of '{reason}'."
                    )
                    status = JobStatus.failed.name

            if not status:
                logging.info("Kubernetes job id: {} succeeded.".format(backend_job_id))
                status = JobStatus.finished.name

        elif job_pod.status.phase == "Failed":
            logging.info("Kubernetes job id: {} failed.".format(backend_job_id))
            status = JobStatus.failed.name

        elif job_pod.status.phase == "Pending":
            for container in container_statuses:
                reason = None
                message = None
                try:
                    reason = container.state.waiting.reason
                    message = container.state.waiting.message
                except AttributeError:
                    pass

                if not reason:
                    continue

                if "ErrImagePull" in reason:
                    logging.warn(
                        f"Container {container.name} in Kubernetes job {backend_job_id} "
                        "failed to fetch image."
                    )
                    status = JobStatus.failed.name
                elif "InvalidImageName" in reason:
                    logging.warn(
                        f"Container {container.name} in Kubernetes job {backend_job_id} "
                        "failed due to invalid image name."
                    )
                    status = JobStatus.failed.name
                elif "CreateContainerConfigError" in reason:
                    logging.warn(
                        f"Container {container.name} in Kubernetes job {backend_job_id} "
                        f"failed due to container configuration error: {message}"
                    )
                    status = JobStatus.failed.name

        return status

    def watch_job_event_stream(self):
        """
        Watch job events from the Kubernetes API.

        This method is used when MultiKueue is enabled, since in that case we can't
        directly monitor the worker pods as they are remote.
        """
        while True:
            logging.info("Starting a new stream request to watch Jobs")

            try:
                w = watch.Watch()
                for event in w.stream(
                    client.BatchV1Api().list_namespaced_job,
                    namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
                    label_selector=f"reana-run-job-workflow-uuid={self.workflow_uuid}",
                ):
                    logging.info(f"New Job event received: {event["type"]}")

                    job = event["object"]
                    job_id = job.metadata.name
                    job_finished = (
                        job.status.succeeded
                        and not job.status.active
                        and not job.status.failed
                    )
                    job_status = (
                        JobStatus.finished.name
                        if job_finished
                        else (
                            JobStatus.failed.name
                            if job.status.failed
                            else JobStatus.running.name
                        )
                    )

                    if self.should_process_job(job):
                        reana_job_id = self.get_reana_job_id(job_id)

                        if job_status == JobStatus.failed.name:
                            self.log_disruption(
                                event["object"].status.conditions, job_id
                            )

                        # TODO: Fetch logs from the remote job pod on the remote worker when MultiKueue supports this
                        logs = self.job_manager_cls.get_logs(job_id)
                        if logs is not None:
                            store_job_logs(reana_job_id, logs)

                        update_job_status(
                            reana_job_id,
                            job_status,
                        )

                        if JobStatus.should_cleanup_job(job_status):
                            self.clean_job(job_id)

            except client.rest.ApiException as e:
                logging.exception(f"Error from Kubernetes API while watching jobs: {e}")
            except Exception as e:
                logging.error(traceback.format_exc())
                logging.error("Unexpected error: {}".format(e))

    def watch_pod_event_stream(self):
        """
        Watch pod events from the Kubernetes API.

        This method is used when MultiKueue is not enabled, since in that case we can
        directly monitor the worker pods as they are running on the local cluster.
        """
        while True:
            try:
                w = watch.Watch()
                for event in w.stream(
                    current_k8s_corev1_api_client.list_namespaced_pod,
                    namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
                    label_selector=f"reana-run-job-workflow-uuid={self.workflow_uuid}",
                ):
                    logging.info("New Pod event received: {0}".format(event["type"]))
                    job_pod = event["object"]

                    # Each job is processed once, when reaching a final state
                    # (either successfully or not)
                    if self.should_process_job_pod(job_pod):
                        job_status = self.get_job_status(job_pod)
                        backend_job_id = self.get_backend_job_id(job_pod)
                        reana_job_id = self.get_reana_job_id(backend_job_id)

                        logs = self.job_manager_cls.get_logs(
                            backend_job_id, job_pod=job_pod
                        )

                        if job_status == JobStatus.failed.name:
                            self.log_disruption(
                                event["object"].status.conditions, backend_job_id
                            )

                        store_job_logs(reana_job_id, logs)
                        update_job_status(reana_job_id, job_status)

                        if JobStatus.should_cleanup_job(job_status):
                            self.clean_job(backend_job_id)
            except client.rest.ApiException as e:
                logging.exception(
                    f"Error from Kubernetes API while watching jobs pods: {e}"
                )
            except Exception as e:
                logging.error(traceback.format_exc())
                logging.error("Unexpected error: {}".format(e))

    def watch_jobs(self, job_db, app=None):
        """Open stream connection to k8s apiserver to watch all jobs status.

        :param job_db: Dictionary which contains all current jobs.
        """
        # If using MultiKueue, watch jobs instead of pods since worker pods could be
        # running on a remote cluster that we can't directly monitor
        if KUEUE_ENABLED:
            self.watch_job_event_stream()
        else:
            self.watch_pod_event_stream()

    @staticmethod
    def log_disruption(conditions, backend_job_id):
        """Log disruption message from Kubernetes event conditions.

        Usually it is pod eviction but can be any of https://kubernetes.io/docs/concepts/workloads/pods/disruptions/#pod-disruption-conditions.

        :param conditions: List of Kubernetes event conditions.
        :param backend_job_id: Backend job ID.
        """
        disruption_target = next(
            (item for item in conditions if item.type == "DisruptionTarget"),
            None,
        )
        if disruption_target:
            logging.warn(
                f"{disruption_target.reason}: Job {backend_job_id} was disrupted: {disruption_target.message}"
            )


condorJobStatus = {
    "Unexpanded": 0,
    "Idle": 1,
    "Running": 2,
    "Removed": 3,
    "Completed": 4,
    "Held": 5,
    "Submission_Error": 6,
}


@singleton
class JobMonitorHTCondorCERN(JobMonitor):
    """HTCondor jobs monitor CERN."""

    def __init__(self, app=None, **kwargs):
        """Initialize HTCondor job monitor thread."""
        self.job_manager_cls = COMPUTE_BACKENDS["htcondorcern"]()
        super(__class__, self).__init__(thread_name="htcondor_job_monitor", app=app)

    def format_condor_job_que_query(self, backend_job_ids):
        """Format HTCondor job que query."""
        base_query = "ClusterId == {} ||"
        query = ""
        for job_id in backend_job_ids:
            query += base_query.format(job_id)
        return query[:-2]

    def watch_jobs(self, job_db, app):
        """Watch currently running HTCondor jobs.

        :param job_db: Dictionary which contains all current jobs.
        """
        ignore_hold_codes = [35, 16]
        statuses_to_skip = ["finished", "failed", "stopped"]
        while True:
            try:
                logging.info("Starting a new stream request to watch Condor Jobs")
                backend_job_ids = [
                    job_dict["backend_job_id"]
                    for id, job_dict in job_db.items()
                    if not job_db[id]["deleted"]
                    and job_db[id]["compute_backend"] == "htcondorcern"
                ]
                future_condor_jobs = app.htcondor_executor.submit(
                    query_condor_jobs, app, backend_job_ids
                )
                condor_jobs = future_condor_jobs.result()
                for job_id, job_dict in job_db.items():
                    if (
                        job_db[job_id]["deleted"]
                        or job_db[job_id]["compute_backend"] != "htcondorcern"
                        or job_db[job_id]["status"] in statuses_to_skip
                    ):
                        continue
                    try:
                        condor_job = next(
                            job
                            for job in condor_jobs
                            if job["ClusterId"] == job_dict["backend_job_id"]
                        )
                    except Exception:
                        msg = "Job with id {} was not found in schedd.".format(
                            job_dict["backend_job_id"]
                        )
                        logging.error(msg)
                        future_job_history = app.htcondor_executor.submit(
                            self.job_manager_cls.find_job_in_history,
                            job_dict["backend_job_id"],
                        )
                        condor_job = future_job_history.result()
                        if condor_job:
                            msg = "Job was found in history. {}".format(str(condor_job))
                            logging.error(msg)
                            update_job_status(job_id, "failed")
                            store_job_logs(job_id, msg)
                        continue
                    if condor_job["JobStatus"] == condorJobStatus["Completed"]:
                        exit_code = condor_job.get(
                            "ExitCode", condor_job.get("ExitStatus")
                        )
                        if exit_code == 0:
                            update_job_status(job_id, "finished")
                        else:
                            logging.info(
                                "Job job_id: {0}, condor_job_id: {1} "
                                "failed".format(job_id, condor_job["ClusterId"])
                            )
                            update_job_status(job_id, "failed")
                        app.htcondor_executor.submit(
                            self.job_manager_cls.spool_output,
                            job_dict["backend_job_id"],
                        ).result()
                        job_logs = app.htcondor_executor.submit(
                            self.job_manager_cls.get_logs,
                            job_dict["backend_job_id"],
                            workspace=job_db[job_id]["obj"].workflow_workspace,
                        )
                        logs = job_logs.result()
                        store_job_logs(job_id, logs)

                        job_db[job_id]["deleted"] = True
                    elif (
                        condor_job["JobStatus"] == condorJobStatus["Held"]
                        and int(condor_job["HoldReasonCode"]) not in ignore_hold_codes
                    ):
                        logging.info("Job was held, will delete and set as failed")
                        self.job_manager_cls.stop(condor_job["ClusterId"])
                        job_db[job_id]["deleted"] = True
                time.sleep(120)
            except Exception as e:
                logging.error("Unexpected error: {}".format(e), exc_info=True)
                time.sleep(120)


slurmJobStatus = {
    "failed": [
        "BOOT_FAIL",
        "CANCELLED",
        "DEADLINE",
        "FAILED",
        "NODE_FAIL",
        "OUT_OF_MEMORY",
        "PREEMPTED",
        "TIMEOUT",
        "SUSPENDED",
        "STOPPED",
    ],
    "finished": ["COMPLETED"],
    "running": ["CONFIGURING", "COMPLETING", "RUNNING", "STAGE_OUT"],
    "idle": [
        "PENDING",
        "REQUEUE_FED",
        "REQUEUE_HOLD",
        "RESV_DEL_HOLD",
        "REQUEUED",
        "RESIZING",
    ],
    # 'REVOKED',
    # 'SIGNALING',
    # 'SPECIAL_EXIT',
}


@singleton
class JobMonitorSlurmCERN(JobMonitor):
    """Slurm jobs monitor CERN."""

    def __init__(self, **kwargs):
        """Initialize Slurm job monitor thread."""
        self.job_manager_cls = COMPUTE_BACKENDS["slurmcern"]()
        super(__class__, self).__init__(thread_name="slurm_job_monitor")

    def watch_jobs(self, job_db, app=None):
        """Use SSH connection to slurm submitnode to monitor jobs.

        :param job_db: Dictionary which contains all running jobs.
        """
        slurm_connection = SSHClient(
            hostname=SLURM_HEADNODE_HOSTNAME,
            port=SLURM_HEADNODE_PORT,
            timeout=SLURM_SSH_TIMEOUT,
            banner_timeout=SLURM_SSH_BANNER_TIMEOUT,
            auth_timeout=SLURM_SSH_AUTH_TIMEOUT,
        )
        statuses_to_skip = ["finished", "failed", "stopped"]
        while True:
            logging.debug("Starting a new stream request to watch Jobs")
            try:
                slurm_jobs = {}
                for id, job_dict in job_db.items():
                    if (
                        not job_db[id]["deleted"]
                        and job_db[id]["compute_backend"] == "slurmcern"
                        and not job_db[id]["status"] in statuses_to_skip
                    ):
                        slurm_jobs[job_dict["backend_job_id"]] = id
                if not slurm_jobs.keys():
                    continue

                for slurm_job_id, job_dict in slurm_jobs.items():
                    slurm_job_status = slurm_connection.exec_command(
                        f"scontrol show job {slurm_job_id} -o | tr ' ' '\n' | grep JobState | cut -f2 -d '='"
                    ).rstrip()
                    job_id = slurm_jobs[slurm_job_id]
                    if slurm_job_status in slurmJobStatus["finished"]:
                        self.job_manager_cls.get_outputs()
                        update_job_status(job_id, "finished")
                        job_db[job_id]["deleted"] = True
                        logs = self.job_manager_cls.get_logs(
                            backend_job_id=slurm_job_id,
                            workspace=job_db[job_id]["obj"].workflow_workspace,
                        )
                        store_job_logs(job_id, logs)
                    if slurm_job_status in slurmJobStatus["failed"]:
                        self.job_manager_cls.get_outputs()
                        update_job_status(job_id, "failed")
                        job_db[job_id]["deleted"] = True
                        logs = self.job_manager_cls.get_logs(
                            backend_job_id=slurm_job_id,
                            workspace=job_db[job_id]["obj"].workflow_workspace,
                        )
                        store_job_logs(job_id, logs)
            except Exception as e:
                logging.error("Unexpected error: {}".format(e), exc_info=True)
                time.sleep(120)


@singleton
class JobMonitorCompute4PUNCH(JobMonitor):
    """HTCondor jobs monitor Compute4PUNCH."""

    def __init__(self, **kwargs):
        """Initialize Compute4PUNCH job monitor thread."""
        self.job_manager_cls = COMPUTE_BACKENDS["compute4punch"]()
        super(__class__, self).__init__(thread_name="compute4punch_job_monitor")

    def watch_jobs(self, job_db, app=None):
        """
        Use SSH connection to Compute4PUNCH login node to monitor jobs.

        :param job_db: Dictionary which contains all running jobs.
        """
        c4p_connection = SSHClient(
            hostname=C4P_LOGIN_NODE_HOSTNAME,
            port=C4P_LOGIN_NODE_PORT,
            timeout=C4P_SSH_TIMEOUT,
            banner_timeout=C4P_SSH_BANNER_TIMEOUT,
            auth_timeout=C4P_SSH_AUTH_TIMEOUT,
            auth_strategy=motley_cue_auth_strategy_factory(
                hostname=C4P_LOGIN_NODE_HOSTNAME
            ),
        )

        while True:
            logging.debug(
                "Starting a new stream request to watch Jobs on Compute4PUNCH"
            )
            try:
                c4p_job_mapping = {
                    job_dict["backend_job_id"]: reana_job_id
                    for reana_job_id, job_dict in job_db.items()
                    if filter_jobs_to_watch(
                        reana_job_id, job_db, compute_backend="compute4punch"
                    )
                }
                c4p_job_statuses = query_c4p_jobs(
                    *c4p_job_mapping.keys(), ssh_client=c4p_connection
                )
                logging.info(f"Compute4PUNCH JobStatuses: {c4p_job_statuses}")
                for c4p_job_id, reana_job_id in c4p_job_mapping.items():
                    job_status = None
                    try:
                        c4p_job_status = c4p_job_statuses[c4p_job_id]["JobStatus"]
                        logging.debug(f"JobStatus of {c4p_job_id} is {c4p_job_status}")
                    except KeyError:
                        msg = f"Job {c4p_job_id} was not found on "
                        msg += f"{C4P_LOGIN_NODE_HOSTNAME}. Assuming it has failed."
                        logging.warning(msg)
                        job_status = "failed"
                        update_job_status(reana_job_id, job_status)
                        job_db[reana_job_id]["deleted"] = True
                        store_job_logs(logs=msg, job_id=reana_job_id)
                    else:
                        if c4p_job_status == str(condorJobStatus["Completed"]):
                            if c4p_job_statuses[c4p_job_id]["ExitCode"] == "0":
                                job_status = "finished"
                            else:
                                job_status = "failed"
                        elif c4p_job_status == str(condorJobStatus["Held"]):
                            if c4p_job_statuses[c4p_job_id]["HoldReasonCode"] == "16":
                                # HoldReasonCode 16 means input files are being spooled.
                                continue
                            logging.debug(
                                f"Job {c4p_job_id} was held, will delete and set as failed"
                            )
                            self.job_manager_cls.stop(c4p_job_id)
                            job_status = "failed"
                        else:
                            continue
                        if job_status in ("failed", "finished"):
                            workflow_workspace = job_db[reana_job_id][
                                "obj"
                            ].workflow_workspace
                            self.job_manager_cls.get_outputs(
                                c4p_connection=c4p_connection,
                                src=self.job_manager_cls.C4P_WORKSPACE_PATH,
                                dest=workflow_workspace,
                            )
                            update_job_status(reana_job_id, job_status)
                            job_db[reana_job_id]["deleted"] = True
                            store_job_logs(
                                logs=self.job_manager_cls.get_logs(
                                    backend_job_id=c4p_job_id,
                                    workspace=workflow_workspace,
                                ),
                                job_id=reana_job_id,
                            )
            except Exception as ex:
                logging.error("Unexpected error: {}".format(ex), exc_info=True)
            time.sleep(120)


def query_c4p_jobs(*backend_job_ids: str, ssh_client: SSHClient):
    """
    Query status information of backend jobs on Compute4PUNCH.

    :param backend_job_ids: List of job ids to query on Compute4PUNCH
    :type backend_job_ids: str
    :param ssh_client: SSH client used to communicate with Compute4PUNCH
    """
    attributes = ("JobStatus", "ClusterId", "ProcId", "ExitCode", "HoldReasonCode")
    attributes_string = " ".join(attributes)

    formatted_backend_job_ids = " ".join(backend_job_ids)

    condor_q_command = f"condor_q {formatted_backend_job_ids} -af:t {attributes_string}"
    condor_history_command = (
        f"condor_history {formatted_backend_job_ids} -af:t {attributes_string}"
    )

    c4p_job_status = ssh_client.exec_command(
        f"{condor_q_command} && {condor_history_command}"
    )

    c4p_queue = {}

    for row in csv_parser(
        input_csv=c4p_job_status.strip(),
        fieldnames=attributes,
        delimiter="\t",
        replacements=dict(undefined=None),
    ):
        row["JobId"] = f"{row['ClusterId']}.{row['ProcId']}"
        c4p_queue[row["JobId"]] = row

    return c4p_queue


def filter_jobs_to_watch(
    id, job_db, compute_backend, statuses_to_skip=("finished", "failed", "stopped")
):
    """
    Filter jobs to watch for job completion.

    :param id: REANA job id
    :type id: str
    :param job_db: REANA job database
    :type job_db: JOB_DB
    :param compute_backend: REANA compute backend used
    :type compute_backend: str
    :param statuses_to_skip: REANA job statuses to skip
    :type statuses_to_skip: tuple[str]
    """
    return job_db[id]["compute_backend"] == compute_backend and not (
        job_db[id]["deleted"] or job_db[id]["status"] in statuses_to_skip
    )


def format_condor_job_que_query(backend_job_ids):
    """Format HTCondor job que query."""
    base_query = "ClusterId == {} ||"
    query = ""
    for job_id in backend_job_ids:
        query += base_query.format(job_id)
    return query[:-2]


def query_condor_jobs(app, backend_job_ids):
    """Query condor jobs."""
    ads = ["ClusterId", "JobStatus", "ExitCode", "ExitStatus", "HoldReasonCode"]
    query = format_condor_job_que_query(backend_job_ids)
    htcondorcern_job_manager_cls = COMPUTE_BACKENDS["htcondorcern"]()
    schedd = htcondorcern_job_manager_cls._get_schedd()
    logging.info("Querying jobs {}".format(backend_job_ids))
    condor_jobs = schedd.xquery(requirements=query, projection=ads)
    return condor_jobs
