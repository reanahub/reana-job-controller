# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2025 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REST API test for REANA-Job-Controller."""

import json
import uuid

import pytest
from flask import current_app, url_for
from kubernetes.client.rest import ApiException
from mock import Mock, patch
from reana_commons.config import REANA_DEFAULT_SNAKEMAKE_ENV_IMAGE
from reana_commons.job_utils import serialise_job_command


def test_delete_job(app, mocked_job):
    """Test valid job deletion."""
    with app.test_request_context(), app.test_client() as client:
        with patch(
            "reana_job_controller.kubernetes_job_manager."
            "current_k8s_batchv1_api_client",
            Mock(),
        ):
            res = client.delete(
                url_for("jobs.delete_job", job_id=mocked_job),
                query_string={
                    "compute_backend": current_app.config["DEFAULT_COMPUTE_BACKEND"]
                },
            )
            assert res.status_code == 204


def test_delete_unknown_job(app):
    """Test delete non existing job."""
    random_job = uuid.uuid4()
    with app.test_request_context(), app.test_client() as client:
        with patch(
            "reana_job_controller.kubernetes_job_manager."
            "current_k8s_batchv1_api_client",
            Mock(),
        ):
            res = client.delete(
                url_for("jobs.delete_job", job_id=random_job),
                query_string={
                    "compute_backend": current_app.config["DEFAULT_COMPUTE_BACKEND"]
                },
            )
            assert res.status_code == 404


def test_delete_job_failed_backend(app, mocked_job):
    """Test delete job simulating a compute backend error."""
    compute_backend_error_msg = "Something went wrong."
    expected_msg = {
        "message": "Connection to compute backend failed:\n{}".format(
            compute_backend_error_msg
        )
    }
    mocked_k8s_client = Mock()
    mocked_k8s_client.delete_namespaced_job = Mock(
        side_effect=ApiException(reason=compute_backend_error_msg)
    )
    with app.test_request_context(), app.test_client() as client:
        with patch(
            "reana_job_controller.kubernetes_job_manager"
            ".current_k8s_batchv1_api_client",
            mocked_k8s_client,
        ):
            res = client.delete(url_for("jobs.delete_job", job_id=mocked_job))
            assert res.json == expected_msg
            assert res.status_code == 502


@patch("reana_job_controller.schemas.REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT", "10")
@patch(
    "reana_job_controller.schemas.REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT", "20"
)
def test_create_job_unsupported_backend(app, job_spec):
    """Test create job with unsupported backend."""
    fake_backend = "htcondorcern"
    expected_msg = "Job submission failed. Backend {} is not supported.".format(
        fake_backend
    )
    job_spec["compute_backend"] = fake_backend
    job_spec["cmd"] = serialise_job_command("ls")
    with app.test_client() as client:
        res = client.post(
            url_for("jobs.create_job"),
            content_type="application/json",
            data=json.dumps(job_spec),
        )
        assert res.json == {"job": expected_msg}
        assert res.status_code == 500


@pytest.mark.parametrize(
    "image",
    [
        REANA_DEFAULT_SNAKEMAKE_ENV_IMAGE,
        "docker.io/library/ubuntu:24.04",
        "",
    ],
)
@patch("reana_job_controller.schemas.REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT", "10")
@patch(
    "reana_job_controller.schemas.REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT", "20"
)
def test_create_job_rejects_unvetted_images(app, job_spec, image):
    """Test that job submission rejects images outside the allowlist."""
    job_spec["docker_img"] = image
    job_spec["cmd"] = serialise_job_command("ls")
    app.config["REANA_VETTED_CONTAINER_IMAGES"] = {
        "enabled": True,
        "allowlist": [],
    }

    with app.test_client() as client:
        response = client.post(
            url_for("jobs.create_job"),
            content_type="application/json",
            data=json.dumps(job_spec),
        )

    assert response.status_code == 403
    assert response.json == {"message": f"Image not allowed: {image}"}


@pytest.mark.parametrize(
    "vetting_config",
    [
        {"enabled": False, "allowlist": []},
        {
            "enabled": True,
            "allowlist": ["docker.io/library/ubuntu:24.04"],
        },
    ],
)
@patch("reana_job_controller.schemas.REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT", "10")
@patch(
    "reana_job_controller.schemas.REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT", "20"
)
def test_create_job_allows_vetted_images(app, job_spec, monkeypatch, vetting_config):
    """Test that allowed images pass vetting and reach job creation."""
    job_spec["compute_backend"] = "test"
    job_spec["docker_img"] = "docker.io/library/ubuntu:24.04"
    job_spec["cmd"] = serialise_job_command("ls")
    app.config["REANA_VETTED_CONTAINER_IMAGES"] = vetting_config
    monkeypatch.setitem(app.config, "SUPPORTED_COMPUTE_BACKENDS", ["test"])
    monkeypatch.setitem(app.config, "COMPUTE_BACKENDS", {"test": lambda: Mock})

    with (
        patch(
            "reana_job_controller.rest.get_cached_user_secrets",
            return_value={},
        ),
        patch(
            "reana_job_controller.rest.job_creation_condition.start_creation",
            return_value=False,
        ),
        app.test_client() as client,
    ):
        response = client.post(
            url_for("jobs.create_job"),
            content_type="application/json",
            data=json.dumps(job_spec),
        )

    assert response.status_code == 400
    assert response.json == {"message": "Cannot create new jobs, shutting down"}
