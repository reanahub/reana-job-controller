# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Kubernetes Job Manager."""

import ast
import logging
import os
import traceback
from typing import Optional

from flask import current_app
from kubernetes import client
from kubernetes.client.models.v1_delete_options import V1DeleteOptions
from kubernetes.client.rest import ApiException
from reana_commons.config import (
    K8S_CERN_EOS_AVAILABLE,
    K8S_CERN_EOS_MOUNT_CONFIGURATION,
    KRB5_STATUS_FILE_LOCATION,
    REANA_JOB_HOSTPATH_MOUNTS,
    REANA_RUNTIME_KUBERNETES_NAMESPACE,
    REANA_RUNTIME_JOBS_KUBERNETES_NODE_LABEL,
    WORKFLOW_RUNTIME_USER_GID,
    WORKFLOW_RUNTIME_USER_UID,
)
from reana_commons.errors import (
    REANAKubernetesMemoryLimitExceeded,
    REANAKubernetesWrongMemoryFormat,
)
from reana_commons.job_utils import (
    validate_kubernetes_memory,
    kubernetes_memory_to_bytes,
)
from reana_commons.k8s.api_client import (
    current_k8s_batchv1_api_client,
    current_k8s_corev1_api_client,
)
from reana_commons.k8s.kerberos import get_kerberos_k8s_config
from reana_commons.k8s.secrets import UserSecretsStore, UserSecrets
from reana_commons.k8s.volumes import (
    get_k8s_cvmfs_volumes,
    get_reana_shared_volume,
    get_workspace_volume,
)
from reana_commons.utils import build_unique_component_name
from retrying import retry

from reana_job_controller.config import (
    REANA_KUBERNETES_JOBS_MEMORY_LIMIT,
    REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT,
    REANA_USER_ID,
    KUEUE_ENABLED,
    KUEUE_DEFAULT_QUEUE,
)
from reana_job_controller.errors import ComputingBackendSubmissionError
from reana_job_controller.job_manager import JobManager


class KubernetesJobManager(JobManager):
    """Kubernetes job management."""

    MAX_NUM_RESUBMISSIONS = 3
    """Maximum number of job submission/creation tries """
    MAX_NUM_JOB_RESTARTS = 0
    """Maximum number of job restarts in case of internal failures."""

    @property
    def secrets(self):
        """Get cached secrets if present, otherwise fetch them from k8s."""
        if self._secrets is None:
            self._secrets = UserSecretsStore.fetch(REANA_USER_ID)
        return self._secrets

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
        kubernetes_memory_limit=None,
        kubernetes_queue=None,
        voms_proxy=False,
        rucio=False,
        kubernetes_job_timeout: Optional[int] = None,
        secrets: Optional[UserSecrets] = None,
        **kwargs,
    ):
        """Instantiate kubernetes job manager.

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
        :param job_name: Name of the job.
        :type job_name: str
        :param kerberos: Decides if kerberos should be provided for job.
        :type kerberos: bool
        :param kubernetes_uid: User ID for job container.
        :type kubernetes_uid: int
        :param kubernetes_memory_limit: Memory limit for job container.
        :type kubernetes_memory_limit: str
        :param kubernetes_queue: If Kueue is enabled of the MultiKueue LocalQueue to send jobs to.
        :type kubernetes_queue: str
        :param kubernetes_job_timeout: Job timeout in seconds.
        :type kubernetes_job_timeout: int
        :param voms_proxy: Decides if a voms-proxy certificate should be
            provided for job.
        :type voms_proxy: bool
        :param rucio: Decides if a rucio environment should be provided
            for job.
        :type rucio: bool
        :param secrets: User secrets, if none they will be fetched from k8s.
        :type secrets: Optional[UserSecrets]
        """
        super(KubernetesJobManager, self).__init__(
            docker_img=docker_img,
            cmd=cmd,
            prettified_cmd=prettified_cmd,
            env_vars=env_vars,
            workflow_uuid=workflow_uuid,
            workflow_workspace=workflow_workspace,
            job_name=job_name,
        )

        self.compute_backend = "Kubernetes"
        self.cvmfs_mounts = cvmfs_mounts
        self.shared_file_system = shared_file_system
        self.kerberos = kerberos
        self.voms_proxy = voms_proxy
        self.rucio = rucio
        self.set_user_id(kubernetes_uid)
        self.set_memory_limit(kubernetes_memory_limit)
        self.kubernetes_queue = kubernetes_queue
        self.workflow_uuid = workflow_uuid
        self.kubernetes_job_timeout = kubernetes_job_timeout
        self._secrets: Optional[UserSecrets] = secrets

    @JobManager.execution_hook
    def execute(self):
        """Execute a job in Kubernetes."""
        backend_job_id = build_unique_component_name("run-job")

        if KUEUE_ENABLED and not (self.kubernetes_queue or KUEUE_DEFAULT_QUEUE):
            logging.error(
                "Kueue is enabled but no queue name was provided. Please set a KUEUE_DEFAULT_QUEUE or ensure that all jobs set a value for kubernetes_queue in their spec."
            )
            raise

        labels = {
            "reana-run-job-workflow-uuid": self.workflow_uuid,
        }

        if KUEUE_ENABLED:
            labels["kueue.x-k8s.io/queue-name"] = (
                f"{self.kubernetes_queue or KUEUE_DEFAULT_QUEUE}-job-queue"
            )

        self.job = {
            "kind": "Job",
            "apiVersion": "batch/v1",
            "metadata": {
                "name": backend_job_id,
                "namespace": REANA_RUNTIME_KUBERNETES_NAMESPACE,
                "labels": labels,
            },
            "spec": {
                "backoffLimit": KubernetesJobManager.MAX_NUM_JOB_RESTARTS,
                "autoSelector": True,
                "template": {
                    "metadata": {
                        "name": backend_job_id,
                        "labels": labels,
                    },
                    "spec": {
                        "automountServiceAccountToken": False,
                        "containers": [
                            {
                                "image": self.docker_img,
                                "command": ["bash", "-c"],
                                "args": [self.cmd],
                                "name": "job",
                                "env": [],
                                "volumeMounts": [],
                                "securityContext": {"allowPrivilegeEscalation": False},
                            }
                        ],
                        "initContainers": [],
                        "volumes": [],
                        "restartPolicy": "Never",
                        # No need to wait a long time for jobs to gracefully terminate
                        "terminationGracePeriodSeconds": 5,
                        "enableServiceLinks": False,
                    },
                },
            },
        }

        secret_env_vars = self.secrets.get_env_secrets_as_k8s_spec()
        job_spec = self.job["spec"]["template"]["spec"]
        job_spec["containers"][0]["env"].extend(secret_env_vars)
        job_spec["volumes"].append(self.secrets.get_file_secrets_volume_as_k8s_specs())

        secrets_volume_mount = self.secrets.get_secrets_volume_mount_as_k8s_spec()
        job_spec["containers"][0]["volumeMounts"].append(secrets_volume_mount)

        if self.env_vars:
            for var, value in self.env_vars.items():
                job_spec["containers"][0]["env"].append({"name": var, "value": value})

        self.add_memory_limit(job_spec)
        self.add_hostpath_volumes()
        self.add_workspace_volume()
        self.add_shared_volume()
        self.add_eos_volume()
        self.add_image_pull_secrets()
        self.add_kubernetes_job_timeout()

        if self.cvmfs_mounts != "false":
            cvmfs_repositories = ast.literal_eval(self.cvmfs_mounts)
            volume_mounts, volumes = get_k8s_cvmfs_volumes(cvmfs_repositories)
            job_spec["containers"][0]["volumeMounts"].extend(volume_mounts)
            job_spec["volumes"].extend(volumes)

        self.job["spec"]["template"]["spec"]["securityContext"] = (
            client.V1PodSecurityContext(
                run_as_group=WORKFLOW_RUNTIME_USER_GID, run_as_user=self.kubernetes_uid
            )
        )

        if self.kerberos:
            self._add_krb5_containers(self.secrets)

        if self.voms_proxy:
            self._add_voms_proxy_init_container(secrets_volume_mount, secret_env_vars)

        if self.rucio:
            self._add_rucio_init_container(secrets_volume_mount, secret_env_vars)

        if REANA_RUNTIME_JOBS_KUBERNETES_NODE_LABEL:
            self.job["spec"]["template"]["spec"][
                "nodeSelector"
            ] = REANA_RUNTIME_JOBS_KUBERNETES_NODE_LABEL

        backend_job_id = self._submit()
        return backend_job_id

    @retry(stop_max_attempt_number=MAX_NUM_RESUBMISSIONS)
    def _submit(self):
        """Submit job and return its backend id."""
        try:
            current_k8s_batchv1_api_client.create_namespaced_job(
                namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE, body=self.job
            )
            return self.job["metadata"]["name"]
        except ApiException:
            logging.exception(
                "An error has occurred while connecting to the Kubernetes API to submit a job"
            )
            raise
        except Exception:
            logging.exception("Unexpected error while submitting a job")
            raise

    @classmethod
    def _get_containers_logs(cls, job_pod) -> Optional[str]:
        """Fetch the logs from all the containers in the given pod.

        :param job_pod: Pod resource coming from Kubernetes.
        """
        try:
            pod_logs = ""
            container_statuses = (job_pod.status.container_statuses or []) + (
                job_pod.status.init_container_statuses or []
            )

            logging.info(f"Grabbing pod {job_pod.metadata.name} logs ...")
            for container in container_statuses:
                # If we are here, it means that either all the containers have finished
                # running or there has been some sort of failure. For this reason we get
                # the logs of all containers, even if they are still running, as the job
                # will not continue running after this anyway.
                if container.state.terminated or container.state.running:
                    container_log = (
                        current_k8s_corev1_api_client.read_namespaced_pod_log(
                            namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
                            name=job_pod.metadata.name,
                            container=container.name,
                        )
                    )
                    pod_logs += "{}: :\n {}\n".format(container.name, container_log)
                    if hasattr(container.state.terminated, "reason"):
                        if container.state.terminated.reason != "Completed":
                            message = "Job pod {} was terminated, reason: {}, message: {}".format(
                                job_pod.metadata.name,
                                container.state.terminated.reason,
                                container.state.terminated.message,
                            )
                            logging.warn(message)
                        pod_logs += "\n{}\n".format(container.state.terminated.reason)
                elif container.state.waiting:
                    # No need to fetch logs, as the container has not started yet.
                    message = "Container {} failed, error: {}".format(
                        container.name, container.state.waiting.message
                    )
                    logging.warn(message)
                    pod_logs += message

            return pod_logs
        except client.rest.ApiException as e:
            logging.error(f"Error from Kubernetes API while getting job logs: {e}")
            return None
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.error("Unexpected error: {}".format(e))
            return None

    @classmethod
    def get_logs(cls, backend_job_id, **kwargs):
        """Return job logs.

        :param backend_job_id: ID of the job in the backend.
        :param kwargs: Additional parameters needed to fetch logs.
            In the case of Kubernetes, the ``job_pod`` parameter can be specified
            to avoid fetching the pod specification from Kubernetes.
        :return: String containing the job logs.
        """
        if "job_pod" in kwargs:
            job_pod = kwargs["job_pod"]
            assert (
                job_pod.metadata.labels["job-name"] == backend_job_id
            ), "Pod does not refer to correct job."
        else:
            job_pods = current_k8s_corev1_api_client.list_namespaced_pod(
                namespace=REANA_RUNTIME_KUBERNETES_NAMESPACE,
                label_selector=f"job-name={backend_job_id}",
            )
            if not job_pods.items:
                logging.error(f"Could not find any pod for job {backend_job_id}")
                return None
            job_pod = job_pods.items[0]

        logs = cls._get_containers_logs(job_pod)

        if job_pod.status.reason == "DeadlineExceeded":
            if not logs:
                logs = ""

            message = (
                f"{job_pod.status.reason}: The job was killed due to exceeding timeout"
            )

            try:
                specified_timeout = job_pod.spec.active_deadline_seconds
                message += f" of {specified_timeout} seconds."
            except AttributeError:
                message += "."
                logging.error(
                    f"Kubernetes job id: {backend_job_id}. Could not get job timeout from Job spec."
                )

            logs += "\n{message}\n"
            logging.warn(message)
            logging.warn(
                f"Kubernetes job id: {backend_job_id} was killed due to timeout."
            )

        return logs

    def stop(backend_job_id, asynchronous=True):
        """Stop Kubernetes job execution.

        :param backend_job_id: Kubernetes job id.
        :param asynchronous: Whether the function waits for the action to be
            performed or does it asynchronously.
        """
        try:
            propagation_policy = "Background" if asynchronous else "Foreground"
            delete_options = V1DeleteOptions(propagation_policy=propagation_policy)
            current_k8s_batchv1_api_client.delete_namespaced_job(
                backend_job_id, REANA_RUNTIME_KUBERNETES_NAMESPACE, body=delete_options
            )
        except ApiException as e:
            logging.error(
                f"An error has occurred while connecting to Kubernetes API to stop a job: {e}"
            )
            raise ComputingBackendSubmissionError(e.reason)

    def add_kubernetes_job_timeout(self):
        """Add job timeout to the job spec."""
        if self.kubernetes_job_timeout:
            self.job["spec"]["template"]["spec"][
                "activeDeadlineSeconds"
            ] = self.kubernetes_job_timeout

    def add_workspace_volume(self):
        """Add workspace volume to a given job spec."""
        volume_mount, volume = get_workspace_volume(self.workflow_workspace)
        self.add_volumes([(volume_mount, volume)])

    def add_shared_volume(self):
        """Add shared CephFS volume to a given job spec."""
        if self.shared_file_system:
            shared_volume = get_reana_shared_volume()
            # check if shared_volume is not already added
            if not any(
                v["name"] == shared_volume["name"]
                for v in self.job["spec"]["template"]["spec"]["volumes"]
            ):
                self.job["spec"]["template"]["spec"]["volumes"].append(shared_volume)

    def add_eos_volume(self):
        """Add EOS volume to a given job spec."""
        if K8S_CERN_EOS_AVAILABLE:
            self.add_volumes(
                [
                    (
                        K8S_CERN_EOS_MOUNT_CONFIGURATION["volumeMounts"],
                        K8S_CERN_EOS_MOUNT_CONFIGURATION["volume"],
                    )
                ]
            )

    def add_image_pull_secrets(self):
        """Attach to the container the configured image pull secrets."""
        image_pull_secrets = []
        for secret_name in current_app.config["IMAGE_PULL_SECRETS"]:
            if secret_name:
                image_pull_secrets.append({"name": secret_name})

        self.job["spec"]["template"]["spec"]["imagePullSecrets"] = image_pull_secrets

    def add_memory_limit(self, job_spec):
        """Add limits.memory to job accordingly."""

        def _set_job_memory_limit(job_spec, memory_limit):
            job_spec["containers"][0]["resources"] = {
                "limits": {
                    "memory": memory_limit,
                }
            }

        if self.kubernetes_memory_limit:
            _set_job_memory_limit(job_spec, self.kubernetes_memory_limit)
        elif REANA_KUBERNETES_JOBS_MEMORY_LIMIT:
            _set_job_memory_limit(job_spec, REANA_KUBERNETES_JOBS_MEMORY_LIMIT)

    def add_hostpath_volumes(self):
        """Add hostPath mounts from configuration to job."""
        volumes_to_mount = []
        for mount in REANA_JOB_HOSTPATH_MOUNTS:
            volume_mount = {
                "name": mount["name"],
                "mountPath": mount.get("mountPath", mount["hostPath"]),
            }
            volume = {"name": mount["name"], "hostPath": {"path": mount["hostPath"]}}
            volumes_to_mount.append((volume_mount, volume))

        self.add_volumes(volumes_to_mount)

    def add_volumes(self, volumes):
        """Add provided volumes to job.

        :param volumes: A list of tuple composed 1st of a Kubernetes
            volumeMount spec and 2nd of Kubernetes volume spec.
        """
        for volume_mount, volume in volumes:
            self.job["spec"]["template"]["spec"]["containers"][0][
                "volumeMounts"
            ].append(volume_mount)
            self.job["spec"]["template"]["spec"]["volumes"].append(volume)

    def _add_krb5_containers(self, secrets):
        """Add krb5 init and renew containers for a job."""
        krb5_config = get_kerberos_k8s_config(
            secrets,
            kubernetes_uid=self.kubernetes_uid,
        )

        self.job["spec"]["template"]["spec"]["volumes"].extend(krb5_config.volumes)
        self.job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"].extend(
            krb5_config.volume_mounts
        )
        # Add the Kerberos token cache file location to the job container
        # so every instance of Kerberos picks it up even if it doesn't read
        # the configuration file.
        self.job["spec"]["template"]["spec"]["containers"][0]["env"].extend(
            krb5_config.env
        )
        # Add Kerberos init container used to generate ticket
        self.job["spec"]["template"]["spec"]["initContainers"].append(
            krb5_config.init_container
        )

        # Add Kerberos renew container to renew ticket periodically for long-running jobs
        self.job["spec"]["template"]["spec"]["containers"].append(
            krb5_config.renew_container
        )

        # Extend the main job command to create a file after it's finished
        self.job["spec"]["template"]["spec"]["containers"][0]["args"] = [
            f"trap 'touch {KRB5_STATUS_FILE_LOCATION}' EXIT; " + self.cmd
        ]

    def _add_voms_proxy_init_container(self, secrets_volume_mount, secret_env_vars):
        """Add sidecar container for a job."""
        ticket_cache_volume = {"name": "voms-proxy-cache", "emptyDir": {}}
        volume_mounts = [
            {
                "name": ticket_cache_volume["name"],
                "mountPath": current_app.config["VOMSPROXY_CERT_CACHE_LOCATION"],
            }
        ]

        voms_proxy_file_path = os.path.join(
            current_app.config["VOMSPROXY_CERT_CACHE_LOCATION"],
            current_app.config["VOMSPROXY_CERT_CACHE_FILENAME"],
        )

        voms_proxy_vo = os.environ.get("VONAME", "")
        voms_proxy_user_file = os.environ.get("VOMSPROXY_FILE", "")

        if voms_proxy_user_file:
            # multi-user deployment mode, where we rely on VOMS proxy file supplied by the user
            voms_proxy_container = {
                "image": current_app.config["VOMSPROXY_CONTAINER_IMAGE"],
                "command": ["/bin/bash"],
                "args": [
                    "-c",
                    'if [ ! -f "/etc/reana/secrets/{voms_proxy_user_file}" ]; then \
                        echo "[ERROR] VOMSPROXY_FILE {voms_proxy_user_file} does not exist in user secrets."; \
                        exit; \
                     fi; \
                     cp /etc/reana/secrets/{voms_proxy_user_file} {voms_proxy_file_path}; \
                     chown {kubernetes_uid} {voms_proxy_file_path}'.format(
                        voms_proxy_user_file=voms_proxy_user_file,
                        voms_proxy_file_path=voms_proxy_file_path,
                        kubernetes_uid=self.kubernetes_uid,
                    ),
                ],
                "name": current_app.config["VOMSPROXY_CONTAINER_NAME"],
                "imagePullPolicy": "IfNotPresent",
                "volumeMounts": [secrets_volume_mount] + volume_mounts,
                "env": secret_env_vars,
            }
        else:
            # single-user deployment mode, where we generate VOMS proxy file in the sidecar from user secrets
            voms_proxy_container = {
                "image": current_app.config["VOMSPROXY_CONTAINER_IMAGE"],
                "command": ["/bin/bash"],
                "args": [
                    "-c",
                    'if [ ! -f "/etc/reana/secrets/userkey.pem" ]; then \
                        echo "[ERROR] File userkey.pem does not exist in user secrets."; \
                        exit; \
                     fi; \
                     if [ ! -f "/etc/reana/secrets/usercert.pem" ]; then \
                        echo "[ERROR] File usercert.pem does not exist in user secrets."; \
                        exit; \
                     fi; \
                     if [ -z "$VOMSPROXY_PASS" ]; then \
                        echo "[ERROR] Environment variable VOMSPROXY_PASS is not set in user secrets."; \
                        exit; \
                     fi; \
                     if [ -z "$VONAME" ]; then \
                        echo "[ERROR] Environment variable VONAME is not set in user secrets."; \
                        exit; \
                     fi; \
                     cp /etc/reana/secrets/userkey.pem /tmp/userkey.pem; \
                         chmod 400 /tmp/userkey.pem; \
                         echo $VOMSPROXY_PASS | base64 -d | voms-proxy-init \
                         --voms {voms_proxy_vo} --key /tmp/userkey.pem \
                         --cert $(readlink -f /etc/reana/secrets/usercert.pem) \
                         --pwstdin --out {voms_proxy_file_path}; \
                         chown {kubernetes_uid} {voms_proxy_file_path}'.format(
                        voms_proxy_vo=voms_proxy_vo.lower(),
                        voms_proxy_file_path=voms_proxy_file_path,
                        kubernetes_uid=self.kubernetes_uid,
                    ),
                ],
                "name": current_app.config["VOMSPROXY_CONTAINER_NAME"],
                "imagePullPolicy": "IfNotPresent",
                "volumeMounts": [secrets_volume_mount] + volume_mounts,
                "env": secret_env_vars,
            }

        self.job["spec"]["template"]["spec"]["volumes"].extend([ticket_cache_volume])
        self.job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"].extend(
            volume_mounts
        )

        # XrootD will look for a valid grid proxy in the location pointed to
        # by the environment variable $X509_USER_PROXY
        self.job["spec"]["template"]["spec"]["containers"][0]["env"].append(
            {"name": "X509_USER_PROXY", "value": voms_proxy_file_path}
        )

        self.job["spec"]["template"]["spec"]["initContainers"].append(
            voms_proxy_container
        )

    def _add_rucio_init_container(self, secrets_volume_mount, secret_env_vars):
        """Add sidecar container for a job."""
        ticket_cache_volume = {"name": "rucio-cache", "emptyDir": {}}
        volume_mounts = [
            {
                "name": ticket_cache_volume["name"],
                "mountPath": current_app.config["RUCIO_CACHE_LOCATION"],
            }
        ]

        rucio_config_file_path = os.path.join(
            current_app.config["RUCIO_CACHE_LOCATION"],
            current_app.config["RUCIO_CFG_CACHE_FILENAME"],
        )

        cern_bundle_path = os.path.join(
            current_app.config["RUCIO_CACHE_LOCATION"],
            current_app.config["RUCIO_CERN_BUNDLE_CACHE_FILENAME"],
        )

        rucio_account = os.environ.get("RUCIO_USERNAME", "")
        voms_proxy_vo = os.environ.get("VONAME", "")

        # Detect Rucio hosts from VO names
        if voms_proxy_vo == "atlas":
            rucio_host = "https://voatlasrucio-server-prod.cern.ch"
            rucio_auth_host = "https://voatlasrucio-auth-prod.cern.ch"
        else:
            rucio_host = f"https://{voms_proxy_vo}-rucio.cern.ch"
            rucio_auth_host = f"https://{voms_proxy_vo}-rucio-auth.cern.ch"

        # Allow overriding detected Rucio hosts by user-provided environment variables
        rucio_host = os.environ.get("RUCIO_RUCIO_HOST", rucio_host)
        rucio_auth_host = os.environ.get("RUCIO_AUTH_HOST", rucio_auth_host)

        rucio_config_container = {
            "image": current_app.config["RUCIO_CONTAINER_IMAGE"],
            "command": ["/bin/bash"],
            "args": [
                "-c",
                'if [ -z "$VONAME" ]; then \
                    echo "[ERROR] Environment variable VONAME is not set in user secrets."; \
                    exit; \
                 fi; \
                 if [ -z "$RUCIO_USERNAME" ]; then \
                    echo "[ERROR] Environment variable RUCIO_USERNAME is not set in user secrets."; \
                    exit; \
                 fi; \
                 export RUCIO_CFG_ACCOUNT={rucio_account} \
                    RUCIO_CFG_CLIENT_VO={voms_proxy_vo} \
                    RUCIO_CFG_RUCIO_HOST={rucio_host} \
                    RUCIO_CFG_AUTH_HOST={rucio_auth_host}; \
                cp /etc/pki/tls/certs/CERN-bundle.pem {cern_bundle_path}; \
                j2 /opt/user/rucio.cfg.j2 > {rucio_config_file_path}'.format(
                    rucio_host=rucio_host,
                    rucio_auth_host=rucio_auth_host,
                    rucio_account=rucio_account,
                    voms_proxy_vo=voms_proxy_vo,
                    cern_bundle_path=cern_bundle_path,
                    rucio_config_file_path=rucio_config_file_path,
                ),
            ],
            "name": current_app.config["RUCIO_CONTAINER_NAME"],
            "imagePullPolicy": "IfNotPresent",
            "volumeMounts": [secrets_volume_mount] + volume_mounts,
            "env": secret_env_vars,
        }

        self.job["spec"]["template"]["spec"]["volumes"].extend([ticket_cache_volume])
        self.job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"].extend(
            volume_mounts
        )

        self.job["spec"]["template"]["spec"]["containers"][0]["env"].append(
            {"name": "RUCIO_CONFIG", "value": rucio_config_file_path}
        )

        self.job["spec"]["template"]["spec"]["initContainers"].append(
            rucio_config_container
        )

    def set_user_id(self, kubernetes_uid):
        """Set user id for job pods. UIDs < 100 are refused for security."""
        if kubernetes_uid and kubernetes_uid >= 100:
            self.kubernetes_uid = kubernetes_uid
        else:
            self.kubernetes_uid = WORKFLOW_RUNTIME_USER_UID

    def set_memory_limit(self, kubernetes_memory_limit):
        """Set memory limit for job pods. Validate if provided format is correct."""
        if kubernetes_memory_limit:
            if not validate_kubernetes_memory(kubernetes_memory_limit):
                msg = f'The "kubernetes_memory_limit" provided {kubernetes_memory_limit} has wrong format.'
                logging.error(
                    "Error while validating Kubernetes memory limit: {}".format(msg)
                )
                raise REANAKubernetesWrongMemoryFormat(msg)

            if REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT:
                custom_job_memory_limit_bytes = kubernetes_memory_to_bytes(
                    kubernetes_memory_limit
                )
                max_custom_job_memory_limit_bytes = kubernetes_memory_to_bytes(
                    REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT
                )
                if custom_job_memory_limit_bytes > max_custom_job_memory_limit_bytes:
                    msg = f'The "kubernetes_memory_limit" provided ({kubernetes_memory_limit}) exceeds the limit ({REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT}).'
                    raise REANAKubernetesMemoryLimitExceeded(msg)

        self.kubernetes_memory_limit = kubernetes_memory_limit
