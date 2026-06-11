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
import re
import uuid

import mock
import pytest
from reana_db.models import Job, JobStatus
from reana_commons.config import (
    KRB5_INIT_CONTAINER_NAME,
    KRB5_RENEW_CONTAINER_NAME,
    WORKFLOW_RUNTIME_USER_UID,
)
from reana_commons.errors import (
    REANAKubernetesCPULimitExceeded,
    REANAKubernetesWrongCPUFormat,
    REANAKubernetesMemoryLimitExceeded,
    REANAKubernetesUIDBelowMinimum,
    REANAKubernetesWrongMemoryFormat,
)
from reana_job_controller.job_manager import JobManager
from reana_job_controller.kubernetes_job_manager import KubernetesJobManager


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
            assert {"name": env_var_key, "value": env_var_value} in env_vars
            assert image == expected_image
            if kerberos:
                assert len(containers) == 2  # main job + sidecar
                assert len(init_containers) == 1
                assert init_containers[0]["name"] == KRB5_INIT_CONTAINER_NAME
                assert len(env_vars) == 7  # KRB5CCNAME is added
                assert "trap" in command[0] and expected_command in command[0]
                assert "kinit -R" in containers[1]["args"][0]
                assert containers[1]["name"] == KRB5_RENEW_CONTAINER_NAME
            else:
                assert len(containers) == 1
                assert len(init_containers) == 0
                # custom env + REANA_WORKSPACE + REANA_WORKFLOW_UUID + DASK_SCHEDULER_URI + two secrets
                assert len(env_vars) == 6
                assert command == [expected_command]


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


def test_execute_unpacked_cvmfs_image(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    empty_user_secrets,
    user0,
    corev1_api_client_with_user_secrets,
    monkeypatch,
):
    """Test execution of a job with an unpacked /cvmfs image."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    cvmfs_image = "/cvmfs/unpacked.cern.ch/registry.hub.docker.com/library/python:3.9"
    expected_command = "echo hello world"
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))

    job_manager = KubernetesJobManager(
        docker_img=cvmfs_image,
        cmd=expected_command,
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
            kubernetes_client.create_namespaced_job.assert_called_once()
            body = kubernetes_client.create_namespaced_job.call_args[1]["body"]
            job_spec = body["spec"]["template"]["spec"]
            container = job_spec["containers"][0]

            # Runner image should be the Apptainer image, not the CVMFS path
            assert container["image"] == "ghcr.io/apptainer/apptainer:v1.5.0"

            # Pod shell should be 'sh' (Apptainer runner is Alpine-based)
            assert container["command"] == ["sh", "-c"]

            # Command should contain apptainer exec with the CVMFS path
            cmd = container["args"][0]
            assert "apptainer exec" in cmd
            assert cvmfs_image in cmd
            assert "--bind /cvmfs" in cmd
            assert f"--bind {workflow_workspace}" in cmd

            # Base64-encoded command should decode back to original
            b64_match = re.search(r"echo (\S+) \| base64 -d \| bash", cmd)
            assert b64_match is not None
            decoded = base64.b64decode(b64_match.group(1)).decode("utf-8")
            assert decoded == expected_command

            # CVMFS volume should be mounted
            cvmfs_mount_paths = [
                m["mountPath"]
                for m in container["volumeMounts"]
                if m.get("name") == "cvmfs"
            ]
            assert any("/cvmfs/unpacked.cern.ch" in path for path in cvmfs_mount_paths)


def test_unpacked_image_merges_cvmfs_mounts(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    empty_user_secrets,
    user0,
    corev1_api_client_with_user_secrets,
    monkeypatch,
):
    """Test that unpacked image auto-adds its CVMFS repo alongside user mounts."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))

    job_manager = KubernetesJobManager(
        docker_img="/cvmfs/unpacked.cern.ch/some/image",
        cmd="ls",
        env_vars={},
        workflow_uuid=workflow_uuid,
        workflow_workspace=workflow_workspace,
        cvmfs_mounts="['sft.cern.ch']",
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
            container = job_spec["containers"][0]

            # Both user-requested and auto-detected repos should be mounted
            cvmfs_mount_paths = [
                m["mountPath"]
                for m in container["volumeMounts"]
                if m.get("name") == "cvmfs"
            ]
            assert any("/cvmfs/sft.cern.ch" in p for p in cvmfs_mount_paths)
            assert any("/cvmfs/unpacked.cern.ch" in p for p in cvmfs_mount_paths)


def test_unpacked_image_special_characters(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    empty_user_secrets,
    user0,
    corev1_api_client_with_user_secrets,
    monkeypatch,
):
    """Test that commands with special characters are safely base64-encoded."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))

    special_cmd = "echo 'hello \"world\"' && cat file.txt | grep -E '^test$'"
    job_manager = KubernetesJobManager(
        docker_img="/cvmfs/unpacked.cern.ch/some/image",
        cmd=special_cmd,
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
            cmd = body["spec"]["template"]["spec"]["containers"][0]["args"][0]

            # Extract and decode the base64 payload
            b64_match = re.search(r"echo (\S+) \| base64 -d \| bash", cmd)
            assert b64_match is not None
            decoded = base64.b64decode(b64_match.group(1)).decode("utf-8")
            assert decoded == special_cmd


def test_normal_image_not_affected():
    """Test that plain Docker images run natively, not via Apptainer."""
    job_manager = KubernetesJobManager(
        docker_img="docker.io/library/busybox",
        cmd="ls",
        env_vars={},
    )
    pod_shell, docker_img, cmd, _ = job_manager._prepare_unpacked_image()
    assert pod_shell == "bash"
    assert docker_img == "docker.io/library/busybox"
    assert cmd == "ls"


@pytest.mark.parametrize(
    "singularity_img",
    [
        "/workspace/images/my_tool.sif",
    ],
)
def test_singularity_image_uses_apptainer_runner(singularity_img):
    """Test that .sif paths use the Apptainer runner."""
    job_manager = KubernetesJobManager(
        docker_img=singularity_img,
        cmd="echo hello",
        env_vars={},
    )
    pod_shell, docker_img, cmd, cvmfs_mounts = job_manager._prepare_unpacked_image()

    assert pod_shell == "sh"
    assert docker_img == "ghcr.io/apptainer/apptainer:v1.5.0"
    assert "apptainer exec" in cmd
    assert singularity_img in cmd
    assert "--bind /cvmfs" not in cmd

    b64_match = re.search(r"echo (\S+) \| base64 -d \| bash", cmd)
    assert b64_match is not None
    decoded = base64.b64decode(b64_match.group(1)).decode("utf-8")
    assert decoded == "echo hello"


def test_singularity_sif_does_not_add_cvmfs_volume(
    app,
    session,
    sample_serial_workflow_in_db,
    sample_workflow_workspace,
    empty_user_secrets,
    user0,
    corev1_api_client_with_user_secrets,
    monkeypatch,
):
    """Test that a .sif image does not trigger CVMFS volume mounting."""
    workflow_uuid = sample_serial_workflow_in_db.id_
    workflow_workspace = next(sample_workflow_workspace(str(workflow_uuid)))
    monkeypatch.setenv("REANA_USER_ID", str(user0.id_))

    job_manager = KubernetesJobManager(
        docker_img="/workspace/my_tool.sif",
        cmd="run_analysis",
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
            container = job_spec["containers"][0]

            assert container["image"] == "ghcr.io/apptainer/apptainer:v1.5.0"
            assert container["command"] == ["sh", "-c"]
            assert "apptainer exec" in container["args"][0]
            assert "--bind /cvmfs" not in container["args"][0]

            # No CVMFS volumes should be mounted
            cvmfs_volumes = [v for v in job_spec["volumes"] if "cvmfs" in v["name"]]
            assert cvmfs_volumes == []
