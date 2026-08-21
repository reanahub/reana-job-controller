# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021, 2022, 2025, 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REST API test for REANA-Job-Controller."""

import json
import uuid
from pathlib import Path

import pytest
from flask import current_app, url_for
from kubernetes.client.rest import ApiException
from mock import Mock, patch
from reana_commons.config import REANA_DEFAULT_SNAKEMAKE_ENV_IMAGE
from reana_commons.errors import REANASecretDoesNotExist
from reana_commons.job_utils import serialise_job_command
from reana_job_controller import rest

from reana_job_controller.job_db import JOB_DB


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


def test_delete_htcondor_job_cleans_file_transfer(app, monkeypatch):
    """Clean local HTCondor staging after explicitly deleting a job."""
    job_id = str(uuid.uuid4())
    job_manager = Mock()
    backend_manager = Mock()
    monkeypatch.setitem(
        JOB_DB,
        job_id,
        {
            "backend_job_id": 123,
            "obj": job_manager,
        },
    )
    monkeypatch.setitem(
        app.config["COMPUTE_BACKENDS"],
        "htcondorcern",
        lambda: backend_manager,
    )

    with app.test_client() as client:
        response = client.delete(
            url_for("jobs.delete_job", job_id=job_id),
            query_string={"compute_backend": "htcondorcern"},
        )

    assert response.status_code == 204
    backend_manager.stop.assert_called_once_with(123)
    job_manager.cleanup_file_transfer.assert_called_once_with()


def test_shutdown_cleans_htcondor_file_transfer(app):
    """Clean local HTCondor staging when the controller shuts down."""
    job_id = str(uuid.uuid4())
    job_manager = Mock(workflow_workspace="/workspace")
    backend_manager = Mock()
    job = {
        "backend_job_id": 123,
        "compute_backend": "htcondorcern",
        "obj": job_manager,
    }
    listed_jobs = [{job_id: {"status": "running"}}]

    with (
        patch.dict(JOB_DB, {job_id: job}, clear=True),
        patch.dict(
            "reana_job_controller.config.COMPUTE_BACKENDS",
            {"htcondorcern": lambda: backend_manager},
            clear=True,
        ),
        patch(
            "reana_job_controller.rest.retrieve_all_jobs",
            return_value=listed_jobs,
        ),
        patch("reana_job_controller.rest.store_job_logs"),
        patch("reana_job_controller.rest.update_job_status"),
        patch("reana_job_controller.rest.job_creation_condition.disable_creation"),
        app.test_client() as client,
    ):
        response = client.get(url_for("jobs.shutdown"))

    assert response.status_code == 200
    backend_manager.stop.assert_called_once_with(123)
    job_manager.cleanup_file_transfer.assert_called_once_with()


@patch("reana_job_controller.schemas.REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT", "10")
@patch(
    "reana_job_controller.schemas.REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT", "20"
)
def test_create_job_unsupported_backend(app, job_spec):
    """Test create job with unsupported backend."""
    fake_backend = "unsupported"
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


@patch("reana_job_controller.schemas.REANA_KUBERNETES_JOBS_TIMEOUT_LIMIT", "10")
@patch(
    "reana_job_controller.schemas.REANA_KUBERNETES_JOBS_MAX_USER_TIMEOUT_LIMIT", "20"
)
def test_create_job_returns_400_for_constructor_time_secret_scope_errors(
    app,
    job_spec,
    monkeypatch,
):
    """Secret scoping errors raised before execute() should still return 400."""

    class ExplodingManager:
        def __init__(self, **kwargs):
            raise REANASecretDoesNotExist(["missing"])

    job_spec["compute_backend"] = "test"
    job_spec["cmd"] = serialise_job_command("ls")
    app.config["REANA_VETTED_CONTAINER_IMAGES"] = {
        "enabled": False,
        "allowlist": [],
    }
    monkeypatch.setitem(app.config, "SUPPORTED_COMPUTE_BACKENDS", ["test"])
    monkeypatch.setitem(
        app.config,
        "COMPUTE_BACKENDS",
        {"test": lambda: ExplodingManager},
    )

    with (
        patch(
            "reana_job_controller.rest.get_cached_user_secrets",
            return_value={},
        ),
        patch(
            "reana_job_controller.rest.job_creation_condition.start_creation"
        ) as start,
        app.test_client() as client,
    ):
        response = client.post(
            url_for("jobs.create_job"),
            content_type="application/json",
            data=json.dumps(job_spec),
        )

    assert response.status_code == 400
    assert response.json == {
        "message": "Operation cancelled. Secrets ['missing'] do not exist."
    }
    start.assert_not_called()


def test_get_cached_user_secrets_rebuilds_from_scoped_pod_secrets(
    tmp_path, monkeypatch
):
    """Scoped sidecar caches should be rebuilt from pod env/files, not k8s fetches."""
    keytab_path = Path(tmp_path) / ".keytab"
    keytab_path.write_bytes(b"keytab file")

    rest._SECRETS_CACHE = None
    monkeypatch.setenv(
        "REANA_USER_SECRETS_TYPES", json.dumps({"username": "env", ".keytab": "file"})
    )
    monkeypatch.setenv("REANA_USER_SECRET_MOUNT_PATH", str(tmp_path))
    monkeypatch.setenv("username", "johndoe")
    monkeypatch.setattr("reana_job_controller.config.REANA_USER_ID", "123")

    with patch("reana_job_controller.rest.UserSecretsStore.fetch") as fetch:
        user_secrets = rest.get_cached_user_secrets()

    assert user_secrets.get_secret("username").value_str == "johndoe"
    assert user_secrets.get_secret(".keytab").value_bytes == b"keytab file"
    fetch.assert_not_called()
    rest._SECRETS_CACHE = None
