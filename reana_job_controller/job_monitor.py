# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job monitoring wrapper."""

import logging
import threading
import time
import traceback

from kubernetes import client, watch
from reana_commons.k8s.api_client import (
    current_k8s_batchv1_api_client,
    current_k8s_corev1_api_client,
)
from reana_db.database import Session
from reana_db.models import Job

from reana_job_controller.config import COMPUTE_BACKENDS
from reana_job_controller.job_db import JOB_DB
from reana_job_controller.utils import SSHClient, singleton


class JobMonitor:
    """Job monitor interface."""

    def __init__(self, thread_name, app=None):
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

    def __init__(self, app=None):
        """Initialize Kubernetes job monitor thread."""
        self.job_manager_cls = COMPUTE_BACKENDS["kubernetes"]()
        super(__class__, self).__init__(thread_name="kubernetes_job_monitor")

    def _get_remaining_jobs(self, compute_backend="kubernetes", statuses_to_skip=None):
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

    def get_reana_job_id(self, backend_job_id):
        """Get REANA job ID.

        :param job_pod: Compute backend job id.
        :type job_pod: str

        :return: REANA job ID.
        :rtype: str
        """
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

    def should_process_job(self, job_pod):
        """Decide whether the job should be processed or not.

        For a job to be processed it has to:
        - Be a job created by this instance, that's why we check the in
          memory DB.
        - It has to be an active job, not having been deleted already.
        - It has to be terminated, otherwise no status or logs can be
          retrieved.

        :param job_pod: Compute backend job object (Kubernetes V1Pod
            https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1Pod.md)

        :return: Boolean representing whether the job should be processed or
            not.
        :rtype: bool
        """
        remaining_jobs = self._get_remaining_jobs()
        backend_job_id = self.get_backend_job_id(job_pod)
        is_job_in_memory_db = self.job_db.get(remaining_jobs.get(backend_job_id))
        is_job_in_remaining_jobs = backend_job_id in remaining_jobs
        return is_job_in_memory_db or is_job_in_remaining_jobs

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

    def get_job_status(self, job_pod):
        """Get Kubernetes based REANA job status."""
        status = None
        backend_job_id = self.get_backend_job_id(job_pod)
        if job_pod.status.phase == "Succeeded":
            logging.info("Kubernetes_job_id: {} succeeded.".format(backend_job_id))
            status = "succeeded"
        elif job_pod.status.phase == "Failed":
            logging.info("Kubernetes job id: {} failed.".format(backend_job_id))
            status = "failed"
        elif job_pod.status.phase == "Pending":
            container_statuses = job_pod.status.container_statuses + (
                job_pod.status.init_container_statuses or []
            )
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
                        status = "failed"
                    elif "InvalidImageName" in reason:
                        logging.info(
                            "Container {} in Kubernetes job {} "
                            "failed due to invalid image name.".format(
                                container.name, backend_job_id
                            )
                        )
                        status = "failed"
            except (AttributeError, TypeError):
                pass

        return status

    def get_job_logs(self, job_pod):
        """Get job pod's containers' logs."""
        try:
            pod_logs = ""
            # job_pod = current_k8s_corev1_api_client.read_namespaced_pod(
            #     namespace='default',
            #     name=job_pod.metadata.name)
            # we probably don't need this call again... FIXME
            container_statuses = job_pod.status.container_statuses + (
                job_pod.status.init_container_statuses or []
            )

            logging.info("Grabbing pod {} logs ...".format(job_pod.metadata.name))
            for container in container_statuses:
                if container.state.terminated:
                    container_log = current_k8s_corev1_api_client.read_namespaced_pod_log(
                        namespace="default",
                        name=job_pod.metadata.name,
                        container=container.name,
                    )
                    pod_logs += "{}: :\n {}\n".format(container.name, container_log)
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
                    namespace="default",
                    label_selector="job-name",
                ):
                    logging.info("New Pod event received: {0}".format(event["type"]))
                    job_pod = event["object"]

                    if not self.should_process_job(job_pod):
                        continue

                    job_status = self.get_job_status(job_pod)
                    if job_status in ["failed", "succeeded"]:
                        backend_job_id = self.get_backend_job_id(job_pod)
                        reana_job_id = self.get_reana_job_id(backend_job_id)
                        logs = self.get_job_logs(job_pod)
                        self.store_job_logs(reana_job_id, logs)
                        self.update_job_status(reana_job_id, job_status)
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

    def __init__(self, app=None):
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
        statuses_to_skip = ["succeeded", "failed"]
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
                            app.htcondor_executor.submit(
                                self.job_manager_cls.spool_output,
                                job_dict["backend_job_id"],
                            )
                            job_db[job_id]["status"] = "succeeded"
                        else:
                            logging.info(
                                "Job job_id: {0}, condor_job_id: {1} "
                                "failed".format(job_id, condor_job["ClusterId"])
                            )
                            job_db[job_id]["status"] = "failed"
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
    "succeeded": ["COMPLETED"],
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

    def __init__(self, app=None):
        """Initialize Slurm job monitor thread."""
        self.job_manager_cls = COMPUTE_BACKENDS["slurmcern"]()
        super(__class__, self).__init__(thread_name="slurm_job_monitor")

    def format_slurm_job_query(self, backend_job_ids):
        """Format Slurm job query."""
        cmd = (
            "sacct --jobs {} --noheader --allocations --parsable "
            "--format State,JobID".format(",".join(backend_job_ids))
        )
        return cmd

    def watch_jobs(self, job_db, app=None):
        """Use SSH connection to slurm submitnode to monitor jobs.

        :param job_db: Dictionary which contains all running jobs.
        """
        slurm_connection = SSHClient(
            hostname=self.job_manager_cls.SLURM_HEADNODE_HOSTNAME,
            port=self.job_manager_cls.SLURM_HEADNODE_PORT,
        )
        statuses_to_skip = ["succeeded", "failed"]
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
                    logging.error("No slurm jobs")
                    continue
                slurm_query_cmd = self.format_slurm_job_query(slurm_jobs.keys())
                stdout = slurm_connection.exec_command(slurm_query_cmd)
                for item in stdout.rstrip().split("\n"):
                    slurm_job_status = item.split("|")[0]
                    slurm_job_id = item.split("|")[1]
                    job_id = slurm_jobs[slurm_job_id]
                    if slurm_job_status in slurmJobStatus["succeeded"]:
                        self.job_manager_cls.get_outputs()
                        job_db[job_id]["status"] = "succeeded"
                        job_db[job_id]["deleted"] = True
                        job_db[job_id]["log"] = self.job_manager_cls.get_logs(
                            backend_job_id=job_dict["backend_job_id"],
                            workspace=job_db[job_id]["obj"].workflow_workspace,
                        )
                        store_logs(logs=job_db[job_id]["log"], job_id=job_id)
                    if slurm_job_status in slurmJobStatus["failed"]:
                        self.job_manager_cls.get_outputs()
                        job_db[job_id]["status"] = "failed"
                        job_db[job_id]["deleted"] = True
                        job_db[job_id]["log"] = self.job_manager_cls.get_logs(
                            backend_job_id=job_dict["backend_job_id"],
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
