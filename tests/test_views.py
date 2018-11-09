# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REST API test for REANA-Job-Controller. """

import uuid

import pytest
from flask import url_for
from kubernetes.client.rest import ApiException
from mock import Mock, patch


def test_delete_job(app, mocked_job):
    """Test valid job deletion."""
    with app.test_client() as client:
        with patch('reana_job_controller.k8s.current_k8s_batchv1_api_client',
                   Mock()):
            res = client.delete(url_for('jobs.delete_job', job_id=mocked_job))
            assert res.status_code == 204


def test_delete_unknown_job(app):
    """Test delete non existing job."""
    random_job = uuid.uuid4()
    with app.test_client() as client:
        with patch('reana_job_controller.k8s.current_k8s_batchv1_api_client',
                   Mock()):
            res = client.delete(url_for('jobs.delete_job', job_id=random_job))
            assert res.status_code == 404


def test_delete_job_failed_backend(app, mocked_job):
    """Test delete job simulating a computing backend error."""
    computing_backend_error_msg = 'Something went wrong.'
    expected_msg = {'message': 'Connection to computing backend failed:\n{}'
                    .format(computing_backend_error_msg)}
    mocked_k8s_client = Mock()
    mocked_k8s_client.delete_namespaced_job = \
        Mock(side_effect=ApiException(reason=computing_backend_error_msg))
    with app.test_client() as client:
        with patch('reana_job_controller.k8s'
                   '.current_k8s_batchv1_api_client', mocked_k8s_client):
            res = client.delete(url_for('jobs.delete_job',
                                        job_id=mocked_job))
            assert res.json == expected_msg
            assert res.status_code == 502
