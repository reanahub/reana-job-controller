# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller Job Monitor tests."""

import uuid

import mock
import pytest

from reana_job_controller.job_monitor import (JobMonitorHTCondorCERN,
                                              JobMonitorKubernetes,
                                              JobMonitorSlurmCERN)


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
    'k8s_phase,k8s_container_state,k8s_logs,pod_logs',
    [
        ('Pending', 'ErrImagePull', 'pull access denied', None),
        ('Pending', 'InvalidImageName', 'couldn\'t parse image', None),
        ('Succeeded', 'Completed', None, 'job finished'),
        ('Failed', 'Error', None, 'job failed')
    ]
)
def test_kubernetes_get_job_logs(k8s_phase, k8s_container_state,
                                 k8s_logs, pod_logs, app,
                                 kubernetes_job_pod):
    """Test retrieval of job logs."""
    k8s_corev1_api_client = mock.MagicMock()
    k8s_corev1_api_client.read_namespaced_pod_log = lambda **kwargs: pod_logs
    with mock.patch.multiple(
            'reana_job_controller.job_monitor',
            current_k8s_corev1_api_client=k8s_corev1_api_client,
            threading=mock.DEFAULT):
        job_monitor_k8s = JobMonitorKubernetes(app=app)
        job_pod = kubernetes_job_pod(k8s_phase, k8s_container_state)
        assert (k8s_logs or pod_logs) in job_monitor_k8s.get_job_logs(job_pod)


@pytest.mark.parametrize(
    'k8s_phase,k8s_container_state,expected_reana_status',
    [
        ('Pending', 'ErrImagePull', 'failed'),
        ('Pending', 'InvalidImageName', 'failed'),
        ('Succeeded', 'Completed', 'succeeded'),
        ('Failed', 'Error', 'failed')
    ]
)
def test_kubernetes_get_job_status(k8s_phase, k8s_container_state,
                                   expected_reana_status, app,
                                   kubernetes_job_pod):
    """Test retrieval of job status."""
    with mock.patch("reana_job_controller.job_monitor.threading"):
        job_monitor_k8s = JobMonitorKubernetes(app=app)
        job_pod = kubernetes_job_pod(k8s_phase, k8s_container_state)
        assert job_monitor_k8s.get_job_status(job_pod) == expected_reana_status


def test_kubernetes_clean_job(app, mocked_job_managers):
    """Test clean jobs in the Kubernetes compute backend."""
    with mock.patch("reana_job_controller.job_monitor."
                    "threading") as threading:
        job_monitor_k8s = JobMonitorKubernetes(app=app)
        job_id = str(uuid.uuid4())
        job_metadata = {'deleted': False,
                        'compute_backend': 'kubernetes',
                        'status': 'succeeded',
                        'backend_job_id': str(uuid.uuid4())}
        job_monitor_k8s.job_db = {job_id: job_metadata}
        job_monitor_k8s.clean_job(job_metadata['backend_job_id'])
        kubernetes_job_manager = mocked_job_managers['kubernetes']()
        assert kubernetes_job_manager.stop.called_once()
        assert job_monitor_k8s.job_db[job_id]['deleted'] is True


@pytest.mark.parametrize(
    'compute_backend,deleted,should_process',
    [
        ('slurm', False, False),
        ('htcondor', False, False),
        ('kubernetes', True, False),
        ('kubernetes', False, True),
    ]
)
def test_kubernetes_should_process_job(app, compute_backend, deleted,
                                       should_process, kubernetes_job_pod):
    """Test should process job."""
    with mock.patch("reana_job_controller.job_monitor."
                    "threading") as threading:
        job_monitor_k8s = JobMonitorKubernetes(app=app)
        job_id = str(uuid.uuid4())
        backend_job_id = str(uuid.uuid4())
        job_metadata = {'deleted': deleted,
                        'compute_backend': compute_backend,
                        'status': 'succeeded',
                        'backend_job_id': backend_job_id}
        job_monitor_k8s.job_db = {job_id: job_metadata}
        job_pod = kubernetes_job_pod('Succeeded', 'Completed',
                                     job_id=backend_job_id)

        assert bool(job_monitor_k8s.should_process_job(job_pod)) == \
            should_process
