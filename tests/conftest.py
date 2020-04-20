# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Pytest configuration for REANA-Job-Controller."""

from __future__ import absolute_import, print_function

import uuid

import mock
import pytest
from kubernetes.client.models.v1_container_state import V1ContainerState
from kubernetes.client.models.v1_container_state_terminated import \
    V1ContainerStateTerminated
from kubernetes.client.models.v1_container_state_waiting import \
    V1ContainerStateWaiting
from kubernetes.client.models.v1_container_status import V1ContainerStatus
from kubernetes.client.models.v1_pod_status import V1PodStatus
from mock import MagicMock

from reana_job_controller.factory import create_app
from reana_job_controller.job_db import JOB_DB


@pytest.fixture()
def mocked_job():
    """Mock existing job."""
    job_id = str(uuid.uuid4())
    JOB_DB[job_id] = MagicMock()
    return job_id


@pytest.fixture()
def job_spec():
    """Job spec dict."""
    job_spec = {
        'experiment': 'experiment',
        'docker_img': 'image',
        'cmd': 'cmd',
        'prettified_cmd': 'prettified_cmd',
        'env_vars': {},
        'workflow_workspace': 'workflow_workspace',
        'job_name': 'job_name',
        'cvmfs_mounts': 'cvmfs_mounts',
        'workflow_uuid': 'workflow_uuid',
    }
    return job_spec


@pytest.fixture(scope="module")
def base_app(tmp_shared_volume_path):
    """Flask application fixture."""
    config_mapping = {
        "SERVER_NAME": "localhost:5000",
        "SECRET_KEY": "SECRET_KEY",
        "TESTING": True,
        "SHARED_VOLUME_PATH": tmp_shared_volume_path,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///testdb.db",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "ORGANIZATIONS": ["default"],
    }
    app_ = create_app(config_mapping=config_mapping)
    return app_


@pytest.fixture
def kubernetes_job_pod():
    """Create a mocked Kubernetes job pod."""
    phases_to_container_state = {
        'Pending': {
            'InvalidImageName': V1ContainerState(
                waiting=V1ContainerStateWaiting(
                    message=('Failed to apply default image tag "img@#": '
                             'couldn\'t parse image reference "img@#": '
                             'invalid reference format'),
                    reason='InvalidImageName')),
            'ErrImagePull': V1ContainerState(
                waiting=V1ContainerStateWaiting(
                    message=('rpc error: code = Unknown desc = Error '
                             'response from daemon: pull access denied for '
                             'private/image, repository does not '
                             'exist or may require docker login: denied:'
                             'requested access to the resource is denied'),
                    reason='ErrImagePull'))
        },
        'Succeeded': {
            'Completed': V1ContainerState(
                terminated=V1ContainerStateTerminated(exit_code=0,
                                                      reason='Completed'))
        },
        'Failed': {
            'Error': V1ContainerState(
                terminated=V1ContainerStateTerminated(exit_code=127,
                                                      reason='Error'))
        },
    }

    def create_job_pod(phase, container_state, init_container_state=None,
                       job_id=None):
        job_pod = MagicMock()
        job_pod.metadata.labels = {'job-name': job_id or str(uuid.uuid4())}

        if phase not in phases_to_container_state.keys():
            raise ValueError(f'{phase} is not a valid pod phase, '
                             f'use one of {phases_to_container_state}')
        job_pod.status = V1PodStatus(phase=phase)

        main_container_status = V1ContainerStatus(
            image='ubuntu:latest', image_id=str(uuid.uuid4()), ready=False,
            state=phases_to_container_state[phase][container_state],
            restart_count=0, name='job')

        job_pod.status.container_statuses = [main_container_status]

        if init_container_state:
            init_container_status = V1ContainerStatus(
                image='ubuntu:latest', image_id=str(uuid.uuid4()), ready=False,
                state=phases_to_container_state[phase][container_state],
                restart_count=0, name='authz')
            job_pod.status.init_container_statuses = [init_container_status]

        return job_pod

    return create_job_pod


@pytest.fixture
def mocked_job_managers():
    """Mock and return all Job managers."""
    kubernetes_job_manager = mock.MagicMock()
    htcondorcern_job_manager = mock.MagicMock()
    slurmcern_job_manager = mock.MagicMock()
    job_managers = {
        'kubernetes': lambda: kubernetes_job_manager,
        'htcondorcern': lambda: htcondorcern_job_manager,
        'slurmcern': lambda: slurmcern_job_manager,
    }
    with mock.patch("reana_job_controller.job_monitor."
                    "COMPUTE_BACKENDS", job_managers):
        yield job_managers
