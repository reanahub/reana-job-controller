# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Kubernetes Job Manager."""

import ast
import logging
import os
import traceback
import uuid

from flask import current_app
from kubernetes import client
from kubernetes.client.models.v1_delete_options import V1DeleteOptions
from kubernetes.client.rest import ApiException
from reana_commons.config import (
    CVMFS_REPOSITORIES,
    K8S_CERN_EOS_AVAILABLE,
    K8S_CERN_EOS_MOUNT_CONFIGURATION,
    REANA_COMPONENT_PREFIX,
    REANA_JOB_HOSTPATH_MOUNTS,
    REANA_RUNTIME_KUBERNETES_NAMESPACE,
    REANA_RUNTIME_KUBERNETES_NODE_LABEL,
    WORKFLOW_RUNTIME_USER_GID,
    WORKFLOW_RUNTIME_USER_UID,
)
from reana_commons.errors import REANAKubernetesWrongMemoryFormat
from reana_commons.job_utils import validate_kubernetes_memory
from reana_commons.k8s.api_client import current_k8s_batchv1_api_client
from reana_commons.k8s.secrets import REANAUserSecretsStore
from reana_commons.k8s.volumes import get_k8s_cvmfs_volume, get_shared_volume
from reana_commons.utils import build_unique_component_name
from retrying import retry

from reana_job_controller.config import REANA_KUBERNETES_JOBS_MEMORY_LIMIT
from reana_job_controller.errors import ComputingBackendSubmissionError
from reana_job_controller.job_manager import JobManager


class KubernetesJobManager(JobManager):
    """Kubernetes job management."""

    MAX_NUM_RESUBMISSIONS = 3
    """Maximum number of job submission/creation tries """
    MAX_NUM_JOB_RESTARTS = 0
    """Maximum number of job restarts in case of internal failures."""

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
        unpacked_img=False,
        voms_proxy=False,
    ):
        """Instanciate kubernetes job manager.

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
        :param voms_proxy: Decides if a voms-proxy certificate should be
            provided for job.
        :type voms_proxy: bool
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
        self.set_user_id(kubernetes_uid)
        self.set_memory_limit(kubernetes_memory_limit)

    @JobManager.execution_hook
    def execute(self):
        """Execute a job in Kubernetes."""

        def _set_job_memory_limit(job_spec, memory_limit):
            job_spec["containers"][0]["resources"] = {
                "limits": {"memory": memory_limit,}
            }

        backend_job_id = build_unique_component_name("run-job")
        self.job = {
            "kind": "Job",
            "apiVersion": "batch/v1",
            "metadata": {
                "name": backend_job_id,
                "namespace": REANA_RUNTIME_KUBERNETES_NAMESPACE,
            },
            "spec": {
                "backoffLimit": KubernetesJobManager.MAX_NUM_JOB_RESTARTS,
                "autoSelector": True,
                "template": {
                    "metadata": {"name": backend_job_id},
                    "spec": {
                        "containers": [
                            {
                                "image": self.docker_img,
                                "command": ["bash", "-c"],
                                "args": [self.cmd],
                                "name": "job",
                                "env": [],
                                "volumeMounts": [],
                            }
                        ],
                        "initContainers": [],
                        "volumes": [],
                        "restartPolicy": "Never",
                    },
                },
            },
        }
        user_id = os.getenv("REANA_USER_ID")
        secrets_store = REANAUserSecretsStore(user_id)

        secret_env_vars = secrets_store.get_env_secrets_as_k8s_spec()
        job_spec = self.job["spec"]["template"]["spec"]
        job_spec["containers"][0]["env"].extend(secret_env_vars)
        job_spec["volumes"].append(secrets_store.get_file_secrets_volume_as_k8s_specs())

        secrets_volume_mount = secrets_store.get_secrets_volume_mount_as_k8s_spec()
        job_spec["containers"][0]["volumeMounts"].append(secrets_volume_mount)

        if self.env_vars:
            for var, value in self.env_vars.items():
                job_spec["containers"][0]["env"].append({"name": var, "value": value})

        if self.kubernetes_memory_limit:
            _set_job_memory_limit(job_spec, self.kubernetes_memory_limit)
        elif REANA_KUBERNETES_JOBS_MEMORY_LIMIT:
            _set_job_memory_limit(job_spec, REANA_KUBERNETES_JOBS_MEMORY_LIMIT)

        self.add_hostpath_volumes()
        self.add_shared_volume()
        self.add_eos_volume()
        self.add_image_pull_secrets()

        if self.cvmfs_mounts != "false":
            cvmfs_map = {}
            for cvmfs_mount_path in ast.literal_eval(self.cvmfs_mounts):
                if cvmfs_mount_path in CVMFS_REPOSITORIES:
                    cvmfs_map[CVMFS_REPOSITORIES[cvmfs_mount_path]] = cvmfs_mount_path

            for repository, mount_path in cvmfs_map.items():
                volume = get_k8s_cvmfs_volume(repository)

                (
                    job_spec["containers"][0]["volumeMounts"].append(
                        {
                            "name": volume["name"],
                            "mountPath": "/cvmfs/{}".format(mount_path),
                            "readOnly": volume["readOnly"],
                        }
                    )
                )
                job_spec["volumes"].append(volume)

        self.job["spec"]["template"]["spec"][
            "securityContext"
        ] = client.V1PodSecurityContext(
            run_as_group=WORKFLOW_RUNTIME_USER_GID, run_as_user=self.kubernetes_uid
        )

        if self.kerberos:
            self._add_krb5_init_container(secrets_volume_mount)

        if self.voms_proxy:
            self._add_voms_proxy_init_container(secrets_volume_mount, secret_env_vars)

        if REANA_RUNTIME_KUBERNETES_NODE_LABEL:
            self.job["spec"]["template"]["spec"][
                "nodeSelector"
            ] = REANA_RUNTIME_KUBERNETES_NODE_LABEL

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
        except ApiException as e:
            logging.error("Error while connecting to Kubernetes" " API: {}".format(e))
        except Exception as e:
            logging.error(traceback.format_exc())
            logging.debug("Unexpected error: {}".format(e))

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
                "An error has occurred while connecting to Kubernetes API "
                "Server \n {}".format(e)
            )
            raise ComputingBackendSubmissionError(e.reason)

    def add_shared_volume(self):
        """Add shared CephFS volume to a given job spec."""
        if self.shared_file_system:
            volume_mount, volume = get_shared_volume(self.workflow_workspace)
            self.add_volumes([(volume_mount, volume)])

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

    def _add_krb5_init_container(self, secrets_volume_mount):
        """Add  sidecar container for a job."""
        krb5_config_map_name = current_app.config["KRB5_CONFIGMAP_NAME"]
        ticket_cache_volume = {"name": "krb5-cache", "emptyDir": {}}
        krb5_config_volume = {
            "name": "krb5-conf",
            "configMap": {"name": krb5_config_map_name},
        }
        volume_mounts = [
            {
                "name": ticket_cache_volume["name"],
                "mountPath": current_app.config["KRB5_TOKEN_CACHE_LOCATION"],
            },
            {
                "name": krb5_config_volume["name"],
                "mountPath": "/etc/krb5.conf",
                "subPath": "krb5.conf",
            },
        ]
        keytab_file = os.environ.get("CERN_KEYTAB")
        cern_user = os.environ.get("CERN_USER")
        krb5_container = {
            "image": current_app.config["KRB5_CONTAINER_IMAGE"],
            "command": [
                "kinit",
                "-kt",
                "/etc/reana/secrets/{}".format(keytab_file),
                "{}@CERN.CH".format(cern_user),
            ],
            "name": current_app.config["KRB5_CONTAINER_NAME"],
            "imagePullPolicy": "IfNotPresent",
            "volumeMounts": [secrets_volume_mount] + volume_mounts,
        }

        self.job["spec"]["template"]["spec"]["volumes"].extend(
            [ticket_cache_volume, krb5_config_volume]
        )
        self.job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"].extend(
            volume_mounts
        )
        # Add the Kerberos token cache file location to the job container
        # so every instance of Kerberos picks it up even if it doesn't read
        # the configuration file.
        self.job["spec"]["template"]["spec"]["containers"][0]["env"].append(
            {
                "name": "KRB5CCNAME",
                "value": os.path.join(
                    current_app.config["KRB5_TOKEN_CACHE_LOCATION"],
                    current_app.config["KRB5_TOKEN_CACHE_FILENAME"].format(
                        self.kubernetes_uid
                    ),
                ),
            }
        )
        self.job["spec"]["template"]["spec"]["initContainers"].append(krb5_container)

    def _add_voms_proxy_init_container(self, secrets_volume_mount, secret_env_vars):
        """Add  sidecar container for a job."""
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

        voms_proxy_vo = os.environ.get("VONAME")

        voms_proxy_container = {
            "image": current_app.config["VOMSPROXY_CONTAINER_IMAGE"],
            "command": ["/bin/bash"],
            "args": [
                "-c",
                "cp /etc/reana/secrets/userkey.pem /tmp/userkey.pem; \
                     chmod 400 /tmp/userkey.pem; \
                     echo $VOMSPROXY_PASS | base64 -d | voms-proxy-init \
                     --voms {voms_proxy_vo} --key /tmp/userkey.pem \
                     --cert $(readlink -f /etc/reana/secrets/usercert.pem) \
                     --pwstdin --out {voms_proxy_file_path}; \
                     chown {kubernetes_uid} {voms_proxy_file_path}".format(
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

    def set_user_id(self, kubernetes_uid):
        """Set user id for job pods. UIDs < 100 are refused for security."""
        if kubernetes_uid and kubernetes_uid >= 100:
            self.kubernetes_uid = kubernetes_uid
        else:
            self.kubernetes_uid = WORKFLOW_RUNTIME_USER_UID

    def set_memory_limit(self, kubernetes_memory_limit):
        """Set memory limit for job pods. Validate if provided format is correct."""
        if kubernetes_memory_limit and not validate_kubernetes_memory(
            kubernetes_memory_limit
        ):
            msg = f"{kubernetes_memory_limit} has wrong format."
            logging.error(
                "Error while validating Kubernetes memory limit: {}".format(msg)
            )
            raise REANAKubernetesWrongMemoryFormat(msg)
        self.kubernetes_memory_limit = kubernetes_memory_limit
