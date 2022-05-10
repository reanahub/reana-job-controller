# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022 CERN.
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
from reana_db.database import Session
from reana_db.models import Job, JobStatus

from reana_job_controller.config import (
    COMPUTE_BACKENDS,
    SLURM_HEADNODE_HOSTNAME,
    SLURM_HEADNODE_PORT,
    SLURM_SSH_TIMEOUT,
    SLURM_SSH_BANNER_TIMEOUT,
    SLURM_SSH_AUTH_TIMEOUT,
)
from reana_job_controller.job_db import JOB_DB
from reana_job_controller.utils import SSHClient, singleton


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

    def get_backend_job_id(self, job_pod):
        """Get the backend job id for the backend object.

        :param job_pod: Compute backend job object (Kubernetes V1Pod
            https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1Pod.md)

        :return: Backend job ID.
        :rtype: str
        """
        return job_pod.metadata.labels["job-name"]

    def store_job_logs(self, reana_job_id, logs):
        """Store logs and update job status.

        :param reana_job_id: Internal REANA job ID.
        :param logs: Job logs.
        :type reana_job_id: str
        :type logs: str
        """
        self.job_db[reana_job_id]["log"] = logs
        store_logs(job_id=reana_job_id, logs=logs)

    def update_job_status(self, reana_job_id, status):
        """Update job status inside RJC.

        :param reana_job_id: Internal REANA job ID.
        :param status: One of the possible status for jobs in REANA
        :type reana_job_id: str
        :type status: str
        """
        self.job_db[reana_job_id]["status"] = status

    def should_process_job(self, job_pod) -> bool:
        """Decide whether the job should be processed or not.

        :param job_pod: Compute backend job object (Kubernetes V1Pod
            https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1Pod.md)
        """
        remaining_jobs = self._get_remaining_jobs(
            statuses_to_skip=[JobStatus.finished.name, JobStatus.failed.name]
        )
        backend_job_id = self.get_backend_job_id(job_pod)
        is_job_in_remaining_jobs = backend_job_id in remaining_jobs

        job_status = self.get_job_status(job_pod)
        is_job_completed = job_status in [
            JobStatus.finished.name,
            JobStatus.failed.name,
        ]

        return (
            is_job_in_remaining_jobs
            and is_job_completed
            and self._all_job_containers_not_running(job_pod)
        )

    @staticmethod
    def _get_job_container_statuses(job_pod):
        return (job_pod.status.container_statuses or []) + (
            job_pod.status.init_container_statuses or []
        )

    def _all_job_containers_not_running(self, job_pod) -> bool:
        return all(
            not container.state.running
            for container in self._get_job_container_statuses(job_pod)
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
            logging.error("Error while connecting to Kubernetes API: {}".format(e))
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.error("Unexpected error: {}".format(e))

    def get_job_status(self, job_pod) -> Optional[str]:
        """Get Kubernetes based REANA job status."""
        status = None
        backend_job_id = self.get_backend_job_id(job_pod)
        if job_pod.status.phase == "Succeeded":
            logging.info("Kubernetes job id: {} succeeded.".format(backend_job_id))
            status = JobStatus.finished.name
        elif job_pod.status.phase == "Failed":
            logging.info("Kubernetes job id: {} failed.".format(backend_job_id))
            status = JobStatus.failed.name
        elif job_pod.status.phase == "Pending":
            container_statuses = self._get_job_container_statuses(job_pod)
            try:
                for container in container_statuses:
                    reason = container.state.waiting.reason
                    if "ErrImagePull" in reason:
                        logging.info(
                            "Container {} in Kubernetes job {} "
                            "failed to fetch image.".format(
                                container.name, backend_job_id
                            )
                        )
                        status = JobStatus.failed.name
                    elif "InvalidImageName" in reason:
                        logging.info(
                            "Container {} in Kubernetes job {} "
                            "failed due to invalid image name.".format(
                                container.name, backend_job_id
                            )
                        )
                        status = JobStatus.failed.name
            except (AttributeError, TypeError):
                pass

        return status

    def _get_containers_logs(self, job_pod) -> Optional[str]:
        try:
            pod_logs = ""
            container_statuses = self._get_job_container_statuses(job_pod)

            logging.info(f"Grabbing pod {job_pod.metadata.name} logs ...")
            for container in container_statuses:
                if container.state.terminated:
                    container_log = (
                        current_k8s_corev1_api_client.read_namespaced_pod_log(
                            namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
                            name=job_pod.metadata.name,
                            container=container.name,
                        )
                    )
                    pod_logs += "{}: :\n {}\n".format(container.name, container_log)
                    if hasattr(container.state.terminated, "reason"):
                        pod_logs += "\n{}\n".format(container.state.terminated.reason)
                elif container.state.waiting:
                    pod_logs += "Container {} failed, error: {}".format(
                        container.name, container.state.waiting.message
                    )

            return pod_logs
        except client.rest.ApiException as e:
            logging.error("Error while connecting to Kubernetes API: {}".format(e))
            return None
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.error("Unexpected error: {}".format(e))
            return None

    def get_job_logs(self, job_pod) -> Optional[str]:
        """Get job logs."""
        logs = self._get_containers_logs(job_pod)

        if job_pod.status.reason == "DeadlineExceeded":
            if not logs:
                logs = ""

            backend_job_id = self.get_backend_job_id(job_pod)
            message = f"\n{job_pod.status.reason}\nThe job was killed due to exceeding timeout"

            try:
                specified_timeout = job_pod.spec.active_deadline_seconds
                message += f" of {specified_timeout} seconds."
            except AttributeError:
                message += "."
                logging.error(
                    f"Kubernetes job id: {backend_job_id}. Could not get job timeout from Job spec."
                )

            logs += message
            logging.info(
                f"Kubernetes job id: {backend_job_id} was killed due to timeout."
            )

        return logs

    def watch_jobs(self, job_db, app=None):
        """Open stream connection to k8s apiserver to watch all jobs status.

        :param job_db: Dictionary which contains all current jobs.
        """
        while True:
            logging.debug("Starting a new stream request to watch Jobs")
            try:
                w = watch.Watch()
                for event in w.stream(
                    current_k8s_corev1_api_client.list_namespaced_pod,
                    namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
                    label_selector=f"reana-run-job-workflow-uuid={self.workflow_uuid}",
                ):
                    logging.info("New Pod event received: {0}".format(event["type"]))
                    job_pod = event["object"]

                    if self.should_process_job(job_pod):
                        job_status = self.get_job_status(job_pod)
                        backend_job_id = self.get_backend_job_id(job_pod)
                        reana_job_id = self.get_reana_job_id(backend_job_id)

                        logs = self.get_job_logs(job_pod)
                        self.store_job_logs(reana_job_id, logs)

                        self.update_job_status(reana_job_id, job_status)

                        if JobStatus.should_cleanup_job(job_status):
                            self.clean_job(backend_job_id)
            except client.rest.ApiException as e:
                logging.error("Error while connecting to Kubernetes API: {}".format(e))
            except Exception as e:
                logging.error(traceback.format_exc())
                logging.error("Unexpected error: {}".format(e))


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
        statuses_to_skip = ["finished", "failed"]
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
                            job_db[job_id]["status"] = "failed"
                            job_db[job_id]["log"] = msg
                        continue
                    if condor_job["JobStatus"] == condorJobStatus["Completed"]:
                        exit_code = condor_job.get(
                            "ExitCode", condor_job.get("ExitStatus")
                        )
                        if exit_code == 0:
                            job_db[job_id]["status"] = "finished"
                        else:
                            logging.info(
                                "Job job_id: {0}, condor_job_id: {1} "
                                "failed".format(job_id, condor_job["ClusterId"])
                            )
                            job_db[job_id]["status"] = "failed"
                        app.htcondor_executor.submit(
                            self.job_manager_cls.spool_output,
                            job_dict["backend_job_id"],
                        ).result()
                        job_logs = app.htcondor_executor.submit(
                            self.job_manager_cls.get_logs,
                            job_dict["backend_job_id"],
                            job_db[job_id]["obj"].workflow_workspace,
                        )
                        job_db[job_id]["log"] = job_logs.result()
                        store_logs(logs=job_db[job_id]["log"], job_id=job_id)

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
    ]
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
        statuses_to_skip = ["finished", "failed"]
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
                        job_db[job_id]["status"] = "finished"
                        job_db[job_id]["deleted"] = True
                        job_db[job_id]["log"] = self.job_manager_cls.get_logs(
                            backend_job_id=slurm_job_id,
                            workspace=job_db[job_id]["obj"].workflow_workspace,
                        )
                        store_logs(logs=job_db[job_id]["log"], job_id=job_id)
                    if slurm_job_status in slurmJobStatus["failed"]:
                        self.job_manager_cls.get_outputs()
                        job_db[job_id]["status"] = "failed"
                        job_db[job_id]["deleted"] = True
                        job_db[job_id]["log"] = self.job_manager_cls.get_logs(
                            backend_job_id=slurm_job_id,
                            workspace=job_db[job_id]["obj"].workflow_workspace,
                        )
                        store_logs(logs=job_db[job_id]["log"], job_id=job_id)
            except Exception as e:
                logging.error("Unexpected error: {}".format(e), exc_info=True)
                time.sleep(120)


def store_logs(logs, job_id):
    """Write logs to DB."""
    try:
        logging.info("Storing job logs: {}".format(job_id))
        Session.query(Job).filter_by(id_=job_id).update(dict(logs=logs))
        Session.commit()
    except Exception as e:
        logging.error("Exception while saving logs: {}".format(str(e)), exc_info=True)


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
