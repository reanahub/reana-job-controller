# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller Job Manager tests."""

import base64
import json
import uuid
from types import SimpleNamespace

import mock
import pytest
from reana_commons.config import (
    KRB5_INIT_CONTAINER_NAME,
    KRB5_RENEW_CONTAINER_NAME,
    WORKFLOW_RUNTIME_USER_GID,
    WORKFLOW_RUNTIME_USER_UID,
)
from reana_db.models import Job, JobStatus
from reana_commons.errors import (
    REANAKubernetesCPULimitExceeded,
    REANAKubernetesWrongCPUFormat,
    REANAKubernetesMemoryLimitExceeded,
    REANAKubernetesUIDBelowMinimum,
    REANAKubernetesWrongMemoryFormat,
)
from reana_job_controller.job_manager import JobManager
from reana_job_controller.kubernetes_job_manager import (
    KubernetesJobManager,
    _get_compatible_kerberos_k8s_config,
)


def _build_user_secret(value, secret_type):
    """Build a mock Kubernetes user secret entry."""
    return {
        "value": base64.b64encode(value.encode()).decode(),
        "type": secret_type,
    }


@pytest.mark.parametrize("kerberos", [False, True])
def test_execute_kubernetes_job(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    user0,
    kerberos_user_secrets,
    corev1_api_client_with_user_secrets,
    monkeypatch,
    kerberos,
):
    """Test execution of Kubernetes job."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    env_var_key = "key"
    env_var_value = "value"
    expected_env_var = {env_var_key: env_var_value}
    expected_image = "docker.io/library/busybox"
    expected_command = "ls"
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))
    job_manager = KubernetesJobManager(
        docker_img=expected_image,
        cmd=expected_command,
        env_vars=expected_env_var,
        workflow_uuid=workflow_uuid,
        workflow_workspace=workflow_workspace,
        kerberos=kerberos,
    )

    with mock.patch(
        "reana_job_controller.kubernetes_job_manager." "current_k8s_batchv1_api_client"
    ) as kubernetes_client:
        with mock.patch(
            "reana_commons.k8s.secrets." "current_k8s_corev1_api_client",
            corev1_api_client_with_user_secrets(kerberos_user_secrets),
        ):
            kubernetes_job_id = job_manager.execute()
            created_job = (
                session.query(Job)
                .filter_by(backend_job_id=kubernetes_job_id)
                .one_or_none()
            )
            assert created_job
            assert created_job.docker_img == expected_image
            assert created_job.cmd == json.dumps(expected_command)
            assert json.dumps(expected_env_var) in created_job.env_vars
            assert created_job.status == JobStatus.created
            kubernetes_client.create_namespaced_job.assert_called_once()
            body = kubernetes_client.create_namespaced_job.call_args[1]["body"]
            init_containers = body["spec"]["template"]["spec"]["initContainers"]
            containers = body["spec"]["template"]["spec"]["containers"]
            env_vars = containers[0]["env"]
            image = containers[0]["image"]
            command = containers[0]["args"]
            container_security_context = containers[0]["securityContext"]
            security_context = body["spec"]["template"]["spec"]["securityContext"]
            assert {"name": env_var_key, "value": env_var_value} in env_vars
            assert image == expected_image
            assert security_context.run_as_user == int(WORKFLOW_RUNTIME_USER_UID)
            assert security_context.run_as_group == int(WORKFLOW_RUNTIME_USER_GID)
            assert container_security_context["runAsNonRoot"] is True
            assert container_security_context["allowPrivilegeEscalation"] is False
            assert container_security_context["capabilities"] == {"drop": ["ALL"]}
            assert container_security_context["seccompProfile"] == {
                "type": "RuntimeDefault"
            }
            if kerberos:
                assert len(containers) == 2  # main job + sidecar
                assert len(init_containers) == 1
                assert init_containers[0]["name"] == KRB5_INIT_CONTAINER_NAME
                assert init_containers[0]["securityContext"] == {
                    "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
                    "runAsUser": int(WORKFLOW_RUNTIME_USER_UID),
                    "runAsNonRoot": True,
                    "allowPrivilegeEscalation": False,
                    "capabilities": {"drop": ["ALL"]},
                    "seccompProfile": {"type": "RuntimeDefault"},
                }
                assert len(env_vars) == 7  # KRB5CCNAME is added
                assert "trap" in command[0] and expected_command in command[0]
                assert "kinit -R" in containers[1]["args"][0]
                assert containers[1]["name"] == KRB5_RENEW_CONTAINER_NAME
                assert containers[1]["securityContext"] == {
                    "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
                    "runAsUser": int(WORKFLOW_RUNTIME_USER_UID),
                    "runAsNonRoot": True,
                    "allowPrivilegeEscalation": False,
                    "capabilities": {"drop": ["ALL"]},
                    "seccompProfile": {"type": "RuntimeDefault"},
                }
            else:
                assert len(containers) == 1
                assert len(init_containers) == 0
                # custom env + REANA_WORKSPACE + REANA_WORKFLOW_UUID + DASK_SCHEDULER_URI + two secrets
                assert len(env_vars) == 6
                assert command == [expected_command]


def test_execute_kubernetes_job_with_voms_proxy_init_container(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    user0,
    corev1_api_client_with_user_secrets,
    monkeypatch,
):
    """Test that the VOMS init container is PSA-restricted."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    voms_user_secrets = {
        "VOMSPROXY_FILE": _build_user_secret("proxy.pem", "env"),
        "proxy.pem": _build_user_secret("proxy data", "file"),
    }
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))
    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
        workflow_uuid=workflow_uuid,
        workflow_workspace=workflow_workspace,
        voms_proxy=True,
    )

    with mock.patch(
        "reana_job_controller.kubernetes_job_manager.current_k8s_batchv1_api_client"
    ) as kubernetes_client:
        with mock.patch(
            "reana_commons.k8s.secrets.current_k8s_corev1_api_client",
            corev1_api_client_with_user_secrets(voms_user_secrets),
        ):
            job_manager.execute()
            body = kubernetes_client.create_namespaced_job.call_args[1]["body"]
            init_container = body["spec"]["template"]["spec"]["initContainers"][0]

            assert init_container["name"] == app.config["VOMSPROXY_CONTAINER_NAME"]
            assert init_container["securityContext"] == {
                "runAsUser": int(WORKFLOW_RUNTIME_USER_UID),
                "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
                "runAsNonRoot": True,
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
                "seccompProfile": {"type": "RuntimeDefault"},
            }


def test_execute_kubernetes_job_with_rucio_init_container(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    user0,
    corev1_api_client_with_user_secrets,
    monkeypatch,
):
    """Test that the Rucio init container is PSA-restricted."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    rucio_user_secrets = {
        "VONAME": _build_user_secret("atlas", "env"),
        "RUCIO_USERNAME": _build_user_secret("johndoe", "env"),
    }
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))
    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
        workflow_uuid=workflow_uuid,
        workflow_workspace=workflow_workspace,
        rucio=True,
    )

    with mock.patch(
        "reana_job_controller.kubernetes_job_manager.current_k8s_batchv1_api_client"
    ) as kubernetes_client:
        with mock.patch(
            "reana_commons.k8s.secrets.current_k8s_corev1_api_client",
            corev1_api_client_with_user_secrets(rucio_user_secrets),
        ):
            job_manager.execute()
            body = kubernetes_client.create_namespaced_job.call_args[1]["body"]
            init_container = body["spec"]["template"]["spec"]["initContainers"][0]

            assert init_container["name"] == app.config["RUCIO_CONTAINER_NAME"]
            assert init_container["securityContext"] == {
                "runAsUser": int(WORKFLOW_RUNTIME_USER_UID),
                "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
                "runAsNonRoot": True,
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
                "seccompProfile": {"type": "RuntimeDefault"},
            }


def test_execute_kubernetes_job_keeps_minimal_container_security_context_when_disabled(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    empty_user_secrets,
    user0,
    corev1_api_client_with_user_secrets,
    monkeypatch,
):
    """Test that disabled security contexts still keep no-new-privileges on jobs."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))
    monkeypatch.setattr(
        "reana_job_controller.kubernetes_job_manager.K8S_USE_SECURITY_CONTEXT",
        False,
    )
    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
        workflow_uuid=workflow_uuid,
        workflow_workspace=workflow_workspace,
    )

    with mock.patch(
        "reana_job_controller.kubernetes_job_manager.current_k8s_batchv1_api_client"
    ) as kubernetes_client:
        with mock.patch(
            "reana_commons.k8s.secrets.current_k8s_corev1_api_client",
            corev1_api_client_with_user_secrets(empty_user_secrets),
        ):
            job_manager.execute()
            body = kubernetes_client.create_namespaced_job.call_args[1]["body"]
            job_spec = body["spec"]["template"]["spec"]

            assert "securityContext" not in job_spec
            assert job_spec["containers"][0]["securityContext"] == {
                "allowPrivilegeEscalation": False
            }


def test_get_compatible_kerberos_k8s_config_supports_old_commons_api(monkeypatch):
    """Retry Kerberos config calls without the new optional kwarg when needed."""
    calls = []

    def old_get_kerberos_k8s_config(secrets, kubernetes_uid):
        calls.append((secrets, kubernetes_uid))
        return "kerberos-config"

    monkeypatch.setattr(
        "reana_job_controller.kubernetes_job_manager.get_kerberos_k8s_config",
        old_get_kerberos_k8s_config,
    )

    kerberos_config = _get_compatible_kerberos_k8s_config("secrets", 1000)

    assert kerberos_config == "kerberos-config"
    assert calls == [("secrets", 1000)]


def test_get_compatible_kerberos_k8s_config_backfills_partial_security_context(
    monkeypatch,
):
    """Backfill missing PSA fields from released commons Kerberos specs."""

    def partially_hardened_get_kerberos_k8s_config(
        secrets, kubernetes_uid, use_security_context=True
    ):
        return SimpleNamespace(
            init_container={
                "securityContext": {
                    "runAsUser": int(kubernetes_uid),
                    "runAsNonRoot": True,
                }
            },
            renew_container={
                "securityContext": {
                    "runAsUser": int(kubernetes_uid),
                    "runAsNonRoot": True,
                }
            },
        )

    monkeypatch.setattr(
        "reana_job_controller.kubernetes_job_manager.get_kerberos_k8s_config",
        partially_hardened_get_kerberos_k8s_config,
    )

    kerberos_config = _get_compatible_kerberos_k8s_config("secrets", 1000)

    expected_security_context = {
        "runAsGroup": int(WORKFLOW_RUNTIME_USER_GID),
        "runAsUser": int(WORKFLOW_RUNTIME_USER_UID),
        "runAsNonRoot": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert (
        kerberos_config.init_container["securityContext"] == expected_security_context
    )
    assert (
        kerberos_config.renew_container["securityContext"] == expected_security_context
    )


def test_stop_kubernetes_job(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    empty_user_secrets,
    user0,
    corev1_api_client_with_user_secrets,
    monkeypatch,
):
    """Test stop of Kubernetes job."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    expected_env_var_name = "env_var"
    expected_env_var_value = "value"
    expected_image = "docker.io/library/busybox"
    expected_command = ["ls"]
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))
    job_manager = KubernetesJobManager(
        docker_img=expected_image,
        cmd=expected_command,
        env_vars={expected_env_var_name: expected_env_var_value},
        workflow_uuid=workflow_uuid,
        workflow_workspace=workflow_workspace,
    )
    with mock.patch(
        "reana_job_controller.kubernetes_job_manager." "current_k8s_batchv1_api_client"
    ) as kubernetes_client:
        with mock.patch(
            "reana_commons.k8s.secrets." "current_k8s_corev1_api_client",
            corev1_api_client_with_user_secrets(empty_user_secrets),
        ):
            kubernetes_job_id = job_manager.execute()
            kubernetes_client.create_namespaced_job.assert_called_once()
            job_manager.stop(kubernetes_job_id)
            kubernetes_client.delete_namespaced_job.assert_called_once()


@mock.patch("reana_job_controller.job_manager.CACHE_ENABLED", True)
def test_execution_hooks():
    """Test hook execution order."""

    class TestJobManger(JobManager):
        @JobManager.execution_hook
        def execute(self):
            self.order_list.append(2)
            job_id = str(uuid.uuid4())
            return job_id

        def before_execution(self):
            self.order_list = []
            self.order_list.append(1)

        def create_job_in_db(self, job_id):
            self.order_list.append(3)

        def cache_job(self):
            self.order_list.append(4)

    job_manager = TestJobManger("docker.io/library/busybox", "ls", {})
    job_manager.execute()
    assert job_manager.order_list == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "k8s_phase,k8s_container_state,k8s_logs,pod_logs",
    [
        ("Pending", "ErrImagePull", "pull access denied", None),
        ("Pending", "InvalidImageName", "couldn't parse image", None),
        ("Succeeded", "Completed", None, "job finished"),
        ("Failed", "Error", None, "job failed"),
    ],
)
def test_kubernetes_get_job_logs(
    k8s_phase, k8s_container_state, k8s_logs, pod_logs, app, kubernetes_job_pod
):
    """Test retrieval of job logs."""
    k8s_corev1_api_client = mock.MagicMock()
    k8s_corev1_api_client.read_namespaced_pod_log = lambda **kwargs: (
        mock.MagicMock(data=pod_logs.encode("utf-8")) if pod_logs else None
    )
    with mock.patch(
        "reana_job_controller.kubernetes_job_manager.current_k8s_corev1_api_client",
        k8s_corev1_api_client,
    ):
        job_pod = kubernetes_job_pod(k8s_phase, k8s_container_state)
        assert (k8s_logs or pod_logs) in KubernetesJobManager.get_logs(
            job_pod.metadata.labels["job-name"], job_pod=job_pod
        )


def test_kubernetes_get_job_logs_preserves_newlines(app, kubernetes_job_pod):
    """Raw pod log bytes are decoded to str with real newlines preserved.

    Guards against kubernetes 36.x's str-deserialiser regression that
    turns ``bytes`` payloads into ``"b'...'"`` repr strings with literal
    backslash-n inside.
    """
    pod_logs_bytes = b"variables\n---------\n(a0,a1,mean)\n"
    k8s_corev1_api_client = mock.MagicMock()
    k8s_corev1_api_client.read_namespaced_pod_log = mock.MagicMock(
        return_value=mock.MagicMock(data=pod_logs_bytes)
    )
    with mock.patch(
        "reana_job_controller.kubernetes_job_manager.current_k8s_corev1_api_client",
        k8s_corev1_api_client,
    ):
        job_pod = kubernetes_job_pod("Succeeded", "Completed")
        logs = KubernetesJobManager.get_logs(
            job_pod.metadata.labels["job-name"], job_pod=job_pod
        )
        assert isinstance(logs, str)
        assert pod_logs_bytes.decode("utf-8") in logs
        assert "b'" not in logs
        assert "\\n" not in logs
        # Lock in the kubernetes 36.x workaround: the call MUST pass
        # ``_preload_content=False`` so we get raw bytes from urllib3
        # instead of the broken str-deserialiser output.
        assert k8s_corev1_api_client.read_namespaced_pod_log.called
        for call in k8s_corev1_api_client.read_namespaced_pod_log.call_args_list:
            assert call.kwargs.get("_preload_content") is False


@pytest.mark.parametrize(
    "cpu_request,max_cpu_request,should_raise,expected_value",
    [
        ("100m", "200m", False, "100m"),  # Valid request
        ("0.1", "0.2", False, "0.1"),  # Valid decimal format
        ("invalid", None, True, None),  # Invalid format
        ("300m", "200m", True, None),  # Exceeds limit
        (None, None, False, None),  # No request specified
    ],
)
def test_set_cpu_request(
    app, monkeypatch, cpu_request, max_cpu_request, should_raise, expected_value
):
    """Test CPU request validation and setting."""
    if max_cpu_request:

        monkeypatch.setattr(
            "reana_job_controller.kubernetes_job_manager.REANA_KUBERNETES_JOBS_MAX_USER_CPU_REQUEST",
            max_cpu_request,
        )

    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
    )

    if should_raise:
        with pytest.raises(
            (REANAKubernetesWrongCPUFormat, REANAKubernetesCPULimitExceeded)
        ):
            job_manager.set_cpu_request(cpu_request)
    else:
        job_manager.set_cpu_request(cpu_request)
        assert job_manager.kubernetes_cpu_request == expected_value


@pytest.mark.parametrize(
    "cpu_limit,max_cpu_limit,should_raise,expected_value",
    [
        ("100m", "200m", False, "100m"),  # Valid limit
        ("0.1", "0.2", False, "0.1"),  # Valid decimal format
        ("invalid", None, True, None),  # Invalid format
        ("300m", "200m", True, None),  # Exceeds limit
        (None, None, False, None),  # No limit specified
    ],
)
def test_set_cpu_limit(
    app, monkeypatch, cpu_limit, max_cpu_limit, should_raise, expected_value
):
    """Test CPU limit validation and setting."""
    if max_cpu_limit:

        monkeypatch.setattr(
            "reana_job_controller.kubernetes_job_manager.REANA_KUBERNETES_JOBS_MAX_USER_CPU_LIMIT",
            max_cpu_limit,
        )
    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
    )

    if should_raise:
        with pytest.raises(
            (REANAKubernetesWrongCPUFormat, REANAKubernetesCPULimitExceeded)
        ):
            job_manager.set_cpu_limit(cpu_limit)
    else:
        job_manager.set_cpu_limit(cpu_limit)
        assert job_manager.kubernetes_cpu_limit == expected_value


@pytest.mark.parametrize(
    "memory_request,max_memory_request,should_raise,expected_value",
    [
        ("100Mi", "200Mi", False, "100Mi"),  # Valid request
        ("1Gi", "2Gi", False, "1Gi"),  # Valid gigabyte format
        ("invalid", None, True, None),  # Invalid format
        ("300Mi", "200Mi", True, None),  # Exceeds limit
        (None, None, False, None),  # No request specified
    ],
)
def test_set_memory_request(
    app, monkeypatch, memory_request, max_memory_request, should_raise, expected_value
):
    """Test memory request validation and setting."""
    if max_memory_request:

        monkeypatch.setattr(
            "reana_job_controller.kubernetes_job_manager.REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_REQUEST",
            max_memory_request,
        )

    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
    )

    if should_raise:
        with pytest.raises(
            (REANAKubernetesWrongMemoryFormat, REANAKubernetesMemoryLimitExceeded)
        ):
            job_manager.set_memory_request(memory_request)
    else:
        job_manager.set_memory_request(memory_request)
        assert job_manager.kubernetes_memory_request == expected_value


@pytest.mark.parametrize(
    "memory_limit,max_memory_limit,should_raise,expected_value",
    [
        ("100Mi", "200Mi", False, "100Mi"),  # Valid limit
        ("1Gi", "2Gi", False, "1Gi"),  # Valid gigabyte format
        ("invalid", None, True, None),  # Invalid format
        ("300Mi", "200Mi", True, None),  # Exceeds limit
        (None, None, False, None),  # No limit specified
    ],
)
def test_set_memory_limit(
    app, monkeypatch, memory_limit, max_memory_limit, should_raise, expected_value
):
    """Test memory limit validation and setting."""
    if max_memory_limit:

        monkeypatch.setattr(
            "reana_job_controller.kubernetes_job_manager.REANA_KUBERNETES_JOBS_MAX_USER_MEMORY_LIMIT",
            max_memory_limit,
        )

    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
    )

    if should_raise:
        with pytest.raises(
            (REANAKubernetesWrongMemoryFormat, REANAKubernetesMemoryLimitExceeded)
        ):
            job_manager.set_memory_limit(memory_limit)
    else:
        job_manager.set_memory_limit(memory_limit)
        assert job_manager.kubernetes_memory_limit == expected_value


@pytest.mark.parametrize(
    "kubernetes_uid,min_user_uid,should_raise,expected_value",
    [
        (1500, 100, False, 1500),  # UID well above minimum accepted as-is.
        (100, 100, False, 100),  # UID equal to minimum accepted.
        (1000, 1000, False, 1000),  # Accepted under admin-raised minimum.
        (None, 100, False, WORKFLOW_RUNTIME_USER_UID),  # No UID: default.
        (50, 100, True, None),  # Below default minimum: refused.
        (500, 1000, True, None),  # Below admin-raised minimum: refused.
        (1100, 1200, True, None),  # Below admin-raised minimum: refused.
        (0, 100, True, None),  # Root refused.
    ],
)
def test_set_user_id(
    app, monkeypatch, kubernetes_uid, min_user_uid, should_raise, expected_value
):
    """Test that the configurable UID minimum is honoured."""
    monkeypatch.setattr(
        "reana_job_controller.kubernetes_job_manager.REANA_KUBERNETES_JOBS_MIN_USER_UID",
        min_user_uid,
    )
    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
    )
    if should_raise:
        with pytest.raises(REANAKubernetesUIDBelowMinimum):
            job_manager.set_user_id(kubernetes_uid)
    else:
        job_manager.set_user_id(kubernetes_uid)
        assert job_manager.kubernetes_uid == expected_value
