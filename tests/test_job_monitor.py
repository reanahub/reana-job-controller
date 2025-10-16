# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller Job Monitor tests."""

import uuid

import mock
import pytest
from kubernetes.client.models import V1PodCondition

from reana_job_controller.job_monitor import (
    JobMonitorHTCondorCERN,
    JobMonitorKubernetes,
    JobMonitorSlurmCERN,
)


def test_if_singelton(app, mocked_job_managers):
    """Test if job monitor classes are singelton."""
    with mock.patch("reana_job_controller.job_monitor.threading"):
        first_k8s_instance = JobMonitorKubernetes(app=app)
        second_k8s_instance = JobMonitorKubernetes(app=app)
        assert first_k8s_instance is second_k8s_instance
        first_htc_instance = JobMonitorHTCondorCERN(app=app)
        second_htc_instance = JobMonitorHTCondorCERN(app=app)
        assert first_htc_instance is second_htc_instance


def test_initialisation(app):
    """Test initialisation of HTCondor job monitor."""
    with mock.patch("reana_job_controller.job_monitor.threading"):
        JobMonitorHTCondorCERN(app=app)
        JobMonitorKubernetes(app=app)
        JobMonitorSlurmCERN(app=app)


@pytest.mark.parametrize(
    "k8s_phase,k8s_container_state,expected_reana_status",
    [
        ("Pending", "ErrImagePull", "failed"),
        ("Pending", "InvalidImageName", "failed"),
        ("Succeeded", "Completed", "finished"),
        ("Failed", "Error", "failed"),
        ("Pending", ["Running", "ErrImagePull"], "failed"),
        ("Succeeded", "OOMKilled", "failed"),
    ],
)
def test_kubernetes_get_job_status(
    k8s_phase, k8s_container_state, expected_reana_status, app, kubernetes_job_pod
):
    """Test retrieval of job status."""
    with mock.patch("reana_job_controller.job_monitor.threading"):
        job_monitor_k8s = JobMonitorKubernetes(app=app)
        job_pod = kubernetes_job_pod(k8s_phase, k8s_container_state)
        assert job_monitor_k8s.get_job_status(job_pod) == expected_reana_status


def test_kubernetes_clean_job(app, mocked_job_managers):
    """Test clean jobs in the Kubernetes compute backend."""
    with mock.patch("reana_job_controller.job_monitor." "threading"):
        job_monitor_k8s = JobMonitorKubernetes(app=app)
        job_id = str(uuid.uuid4())
        job_metadata = {
            "deleted": False,
            "compute_backend": "kubernetes",
            "status": "finished",
            "backend_job_id": str(uuid.uuid4()),
        }
        job_monitor_k8s.job_db = {job_id: job_metadata}
        job_monitor_k8s.clean_job(job_metadata["backend_job_id"])
        kubernetes_job_manager = mocked_job_managers["kubernetes"]()
        assert kubernetes_job_manager.stop.called_once()
        assert job_monitor_k8s.job_db[job_id]["deleted"] is True


@pytest.mark.parametrize(
    "compute_backend,deleted,should_process",
    [
        ("slurm", False, False),
        ("htcondor", False, False),
        ("kubernetes", True, False),
        ("kubernetes", False, True),
    ],
)
def test_kubernetes_should_process_job(
    app, compute_backend, deleted, should_process, kubernetes_job_pod
):
    """Test should process job."""
    with mock.patch("reana_job_controller.job_monitor.threading"):
        job_monitor_k8s = JobMonitorKubernetes(app=app)
        job_id = str(uuid.uuid4())
        backend_job_id = str(uuid.uuid4())
        job_metadata = {
            "deleted": deleted,
            "compute_backend": compute_backend,
            "status": "running",
            "backend_job_id": backend_job_id,
        }
        job_monitor_k8s.job_db = {job_id: job_metadata}
        job_pod_event = kubernetes_job_pod(
            "Succeeded", "Completed", job_id=backend_job_id
        )

        assert (
            bool(job_monitor_k8s.should_process_job_pod(job_pod_event))
            == should_process
        )


@pytest.mark.parametrize(
    "conditions,is_call_expected,expected_message",
    [
        (
            [
                V1PodCondition(
                    type="PodScheduled",
                    status="True",
                ),
                V1PodCondition(
                    type="DisruptionTarget",
                    status="True",
                    reason="EvictionByEvictionAPI",
                    message="Eviction API: evicting",
                ),
                V1PodCondition(
                    type="Initialized",
                    status="True",
                ),
            ],
            True,
            "EvictionByEvictionAPI: Job backend_job_id was disrupted: Eviction API: evicting",
        ),
        (
            [
                V1PodCondition(
                    type="PodScheduled",
                    status="True",
                ),
                V1PodCondition(
                    type="Initialized",
                    status="True",
                ),
            ],
            False,
            "",
        ),
        (
            [],
            False,
            "",
        ),
    ],
)
def test_log_disruption_evicted(conditions, is_call_expected, expected_message):
    """Test logging of disruption target condition."""
    with (
        mock.patch("reana_job_controller.job_monitor.threading"),
        mock.patch("reana_job_controller.job_monitor.logging.warn") as log_mock,
    ):
        job_monitor_k8s = JobMonitorKubernetes(app=None)
        job_monitor_k8s.log_disruption(conditions, "backend_job_id")
        if is_call_expected:
            log_mock.assert_called_with(expected_message)
        else:
            log_mock.assert_not_called()


@pytest.mark.parametrize(
    "job_succeeded,job_failed,job_active,compute_backend,deleted,should_process",
    [
        # Successful job - should be processed
        (1, None, None, "kubernetes", False, True),
        # Failed job - should be processed
        (None, 1, None, "kubernetes", False, True),
        # Active job (still running) - should not be processed
        (None, None, 1, "kubernetes", False, False),
        # Successful but still active - should not be processed
        (1, None, 1, "kubernetes", False, False),
        # Failed but still active - should not be processed
        (None, 1, 1, "kubernetes", False, False),
        # Successful job but already deleted - should not be processed
        (1, None, None, "kubernetes", True, False),
        # Failed job but already deleted - should not be processed
        (None, 1, None, "kubernetes", True, False),
        # Successful job but wrong backend - should not be processed
        (1, None, None, "slurm", False, False),
        # Failed job but wrong backend - should not be processed
        (None, 1, None, "htcondor", False, False),
    ],
)
def test_kubernetes_should_process_job_with_kueue(
    app, job_succeeded, job_failed, job_active, compute_backend, deleted, should_process
):
    """Test should_process_job method for Kubernetes Job objects (used when KUEUE_ENABLED)."""
    with mock.patch("reana_job_controller.job_monitor.threading"):
        job_monitor_k8s = JobMonitorKubernetes(app=app)
        job_id = str(uuid.uuid4())
        backend_job_id = str(uuid.uuid4())
        job_metadata = {
            "deleted": deleted,
            "compute_backend": compute_backend,
            "status": "running",
            "backend_job_id": backend_job_id,
        }
        job_monitor_k8s.job_db = {job_id: job_metadata}

        # Create a mock Kubernetes Job object
        job = mock.MagicMock()
        job.metadata.name = backend_job_id
        job.status.succeeded = job_succeeded
        job.status.failed = job_failed
        job.status.active = job_active

        assert bool(job_monitor_k8s.should_process_job(job)) == should_process
