# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018, 2019, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Rest API endpoint for job management."""

import copy
import json
import logging

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import OperationalError
from reana_commons.errors import (
    REANAKubernetesMemoryLimitExceeded,
    REANAKubernetesWrongMemoryFormat,
)

from reana_job_controller.errors import ComputingBackendSubmissionError
from reana_job_controller.job_db import (
    JOB_DB,
    job_exists,
    job_is_cached,
    retrieve_all_jobs,
    retrieve_backend_job_id,
    retrieve_job,
    retrieve_job_logs,
)
from reana_job_controller.schemas import Job, JobRequest
from reana_job_controller.utils import update_workflow_logs

blueprint = Blueprint("jobs", __name__)

job_request_schema = JobRequest()
job_schema = Job()


@blueprint.route("/job_cache", methods=["GET"])
def check_if_cached():
    r"""Check if job is cached.

    ---
    get:
      summary: Returns boolean depicting if job is in cache.
      description: >-
        This resource takes a job specification and the
        workflow json, and checks if the job to be created,
        already exists in the cache.
      operationId: check_if_cached
      parameters:
       - name: job_spec
         in: query
         description: Required. Specification of the job.
         required: true
         type: string
       - name: workflow_json
         in: query
         description: Required. Specification of the workflow.
         required: true
         type: string
       - name: workflow_workspace
         in: query
         description: Required. Path to workflow workspace.
         required: true
         type: string
      produces:
       - application/json
      responses:
        200:
          description: >-
            Request succeeded. Returns boolean depicting if job is in
            cache.
          examples:
            application/json:
              {
                "cached": True,
                "result_path": "/reana/default/0000/xe2123d/archive/asd213"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
        500:
          description: >-
            Request failed. Internal controller error.

    """
    job_spec = json.loads(request.args["job_spec"])
    workflow_json = json.loads(request.args["workflow_json"])
    workflow_workspace = request.args["workflow_workspace"]
    result = job_is_cached(job_spec, workflow_json, workflow_workspace)
    if result:
        return (
            jsonify(
                {
                    "cached": True,
                    "result_path": result["result_path"],
                    "job_id": result["job_id"],
                }
            ),
            200,
        )
    else:
        return jsonify({"cached": False, "result_path": None}), 200


@blueprint.route("/jobs", methods=["GET"])
def get_jobs():  # noqa
    r"""Get all active jobs.

    ---
    get:
      summary: Returns list of all active jobs.
      description: >-
        This resource is not expecting parameters and it will return a list
        representing all active jobs in JSON format.
      operationId: get_jobs
      produces:
       - application/json
      responses:
        200:
          description: >-
            Request succeeded. The response contains the list of all active
            jobs.
          schema:
            type: array
            items:
              $ref: '#/definitions/Job'
          examples:
            application/json:
              {
                "jobs": {
                  "1612a779-f3fa-4344-8819-3d12fa9b9d90": {
                    "cmd": "date",
                    "cvmfs_mounts": ['atlas.cern.ch', 'atlas-condb.cern.ch'],
                    "docker_img": "busybox",
                    "job_id": "1612a779-f3fa-4344-8819-3d12fa9b9d90",
                    "max_restart_count": 3,
                    "restart_count": 0,
                    "status": "finished"
                  },
                  "2e4bbc1d-db5e-4ee0-9701-6e2b1ba55c20": {
                    "cmd": "date",
                    "cvmfs_mounts": ['atlas.cern.ch', 'atlas-condb.cern.ch'],
                    "docker_img": "busybox",
                    "job_id": "2e4bbc1d-db5e-4ee0-9701-6e2b1ba55c20",
                    "max_restart_count": 3,
                    "restart_count": 0,
                    "status": "started"
                  }
                }
              }
    """
    return jsonify({"jobs": retrieve_all_jobs()}), 200


@blueprint.route("/jobs", methods=["POST"])
def create_job():  # noqa
    r"""Create a new job.

    ---
    post:
      summary: Creates a new job.
      description: >-
        This resource is expecting JSON data with all the necessary information
        of a new job.
      operationId: create_job
      consumes:
       - application/json
      produces:
       - application/json
      parameters:
       - name: job
         in: body
         description: Information needed to instantiate a Job
         required: true
         schema:
           $ref: '#/definitions/JobRequest'
      responses:
        201:
          description: Request succeeded. The job has been launched.
          schema:
            type: object
            properties:
              job_id:
                type: string
          examples:
            application/json:
              {
                "job_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
              }
        400:
          description: >-
            Request failed. The incoming data specification seems malformed.
        500:
          description: >-
            Request failed. Internal controller error. The job could probably
            not have been allocated.
    """
    json_data = request.get_json()
    if not json_data:
        return jsonify({"message": "Empty request"}), 400

    # Validate and deserialize input
    job_request, errors = job_request_schema.load(json_data)
    if errors:
        return jsonify({"message": errors}), 400

    compute_backend = job_request.get(
        "compute_backend", current_app.config["DEFAULT_COMPUTE_BACKEND"]
    )
    job_request.pop("compute_backend", None)
    if compute_backend not in current_app.config["SUPPORTED_COMPUTE_BACKENDS"]:
        msg = "Job submission failed. Backend {} is not supported.".format(
            compute_backend
        )
        logging.error(msg, exc_info=True)
        update_workflow_logs(job_request["workflow_uuid"], msg)
        return jsonify({"job": msg}), 500
    with current_app.app_context():
        job_manager_cls = current_app.config["COMPUTE_BACKENDS"][compute_backend]()
        try:
            job_obj = job_manager_cls(**job_request)
        except REANAKubernetesMemoryLimitExceeded as e:
            return jsonify({"message": e.message}), 403
        except REANAKubernetesWrongMemoryFormat as e:
            return jsonify({"message": e.message}), 400
    try:
        backend_jod_id = job_obj.execute()
    except OperationalError as e:
        msg = f"Job submission failed because of DB connection issues. \n{e}"
        logging.error(msg, exc_info=True)
        return jsonify({"message": msg}), 500
    except Exception as e:
        msg = f"Job submission failed. \n{e}"
        logging.error(msg, exc_info=True)
        return jsonify({"message": msg}), 500
    if job_obj:
        job = copy.deepcopy(job_request)
        job["status"] = "started"
        job["restart_count"] = 0
        job["max_restart_count"] = 3
        job["deleted"] = False
        job["obj"] = job_obj
        job["job_id"] = job_obj.job_id
        job["backend_job_id"] = backend_jod_id
        job["compute_backend"] = compute_backend
        JOB_DB[str(job["job_id"])] = job
        job_monitor_cls = current_app.config["JOB_MONITORS"][compute_backend]()
        job_monitor_cls(
            app=current_app._get_current_object(),
            workflow_uuid=job_request["workflow_uuid"],
        )
        return jsonify({"job_id": job["job_id"]}), 201
    else:
        return jsonify({"job": "Could not be allocated"}), 500


@blueprint.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):  # noqa
    r"""Get a job.

    ---
    get:
      summary: Returns details about a given job.
      description: >-
        This resource is expecting the job's UUID as a path parameter. Its
        information will be served in JSON format.
      operationId: get_job
      produces:
       - application/json
      parameters:
       - name: job_id
         in: path
         description: Required. ID of the job.
         required: true
         type: string
      responses:
        200:
          description: >-
            Request succeeded. The response contains details about the given
            job ID.
          schema:
            $ref: '#/definitions/Job'
          examples:
            application/json:
              "job": {
                "cmd": "date",
                "cvmfs_mounts": ['atlas.cern.ch', 'atlas-condb.cern.ch'],
                "docker_img": "busybox",
                "job_id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac",
                "max_restart_count": 3,
                "restart_count": 0,
                "status": "started"
              }
        404:
          description: Request failed. The given job ID does not seem to exist.
          examples:
            application/json:
              "message": >-
                The job cdcf48b1-c2f3-4693-8230-b066e088444c doesn't exist
    """
    if job_exists(job_id):
        jobdict = retrieve_job(job_id)
        return jsonify(jobdict), 200
    else:
        return jsonify({"message": "The job {} doesn't exist".format(job_id)}), 400


@blueprint.route("/jobs/<job_id>/logs", methods=["GET"])
def get_logs(job_id):  # noqa
    r"""Job logs.

    ---
    get:
      summary: Returns the logs for a given job.
      description: >-
        This resource is expecting the job's UUID as a path parameter. Its
        information will be served in JSON format.
      operationId: get_logs
      produces:
       - application/json
      parameters:
       - name: job_id
         in: path
         description: Required. ID of the job.
         required: true
         type: string
      responses:
        200:
          description: >-
            Request succeeded. The response contains the logs for the given
            job.
          examples:
            application/json:
              "log": "Tue May 16 13:52:00 CEST 2017\n"
        404:
          description: Request failed. The given job ID does not seem to exist.
          examples:
            application/json:
              "message": >-
                The job cdcf48b1-c2f3-4693-8230-b066e088444c doesn't exist
    """
    if job_exists(job_id):
        return retrieve_job_logs(job_id)
    else:
        return jsonify({"message": "The job {} doesn't exist".format(job_id)}), 404


@blueprint.route("/jobs/<job_id>/", methods=["DELETE"])
def delete_job(job_id):  # noqa
    r"""Delete a given job.

    ---
    delete:
      summary: Deletes a given job.
      description: >-
        This resource expects the `job_id` of the job to be deleted.
      operationId: delete_job
      consumes:
       - application/json
      produces:
       - application/json
      parameters:
       - name: job_id
         in: path
         description: Required. ID of the job to be deleted.
         required: true
         type: string
       - name: compute_backend
         in: query
         description: Job compute backend.
         required: false
         type: string
      responses:
        204:
          description: >-
            Request accepted. A request to delete the job has been sent to the
              compute backend.
        404:
          description: Request failed. The given job ID does not seem to exist.
          examples:
            application/json:
              "message": >-
                The job cdcf48b1-c2f3-4693-8230-b066e088444c doesn't exist
        502:
          description: >-
            Request failed. Something went wrong while calling the compute
            backend.
          examples:
            application/json:
              "message": >-
                Connection to compute backend failed:
                [reason]
    """
    if job_exists(job_id):
        try:
            compute_backend = request.args.get(
                "compute_backend", current_app.config["DEFAULT_COMPUTE_BACKEND"]
            )
            backend_job_id = retrieve_backend_job_id(job_id)
            job_manager_cls = current_app.config["COMPUTE_BACKENDS"][compute_backend]()
            job_manager_cls.stop(backend_job_id)
            return jsonify(), 204
        except ComputingBackendSubmissionError as e:
            return (
                jsonify(
                    {"message": "Connection to compute backend failed:\n{}".format(e)}
                ),
                502,
            )
    else:
        return jsonify({"message": "The job {} doesn't exist".format(job_id)}), 404


@blueprint.route("/apispec", methods=["GET"])
def get_openapi_spec():
    """Get OpenAPI Spec."""
    return jsonify(current_app.config["OPENAPI_SPEC"])
