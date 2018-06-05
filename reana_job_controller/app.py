# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017 CERN.
#
# REANA is free software; you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# REANA is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# REANA; if not, write to the Free Software Foundation, Inc., 59 Temple Place,
# Suite 330, Boston, MA 02111-1307, USA.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization or
# submit itself to any jurisdiction.

"""Rest API endpoint for job management."""

import copy
import json
import logging
import threading
import uuid

from flask import Flask, abort, jsonify, request
from reana_commons.database import Session
from reana_commons.models import Job as JobTable

from reana_job_controller.k8s import (create_api_client, instantiate_job,
                                      watch_jobs)
from reana_job_controller.schemas import Job, JobRequest
from reana_job_controller.spec import build_openapi_spec

app = Flask(__name__)
app.secret_key = "mega secret key"
JOB_DB = {}

job_request_schema = JobRequest()
job_schema = Job()


def retrieve_job(job_id):
    """Retrieve job from DB by id.

    :param job_id: UUID which identifies the job to be retrieved.
    :returns: Job object identified by `job_id`.
    """
    job = JOB_DB[job_id]
    return {
        "cmd": job['cmd']
        if job.get('cmd') else '',
        "cvmfs_mounts": job['cvmfs_mounts']
        if job.get('cvmfs_mounts') else [],
        "docker_img": job['docker_img'],
        "experiment": job['experiment'],
        "job_id": job['job_id'],
        "max_restart_count": job['max_restart_count'],
        "restart_count": job['restart_count'],
        "status": job['status']
    }


def retrieve_all_jobs():
    """Retrieve all jobs in the DB.

    :return: A list with all current job objects.
    """
    job_list = []
    for job_id in JOB_DB:
        job = JOB_DB[job_id]
        job_list.append({
            job_id: {
                "cmd": job['cmd']
                if job.get('cmd') else '',
                "cvmfs_mounts": job['cvmfs_mounts']
                if job.get('cvmfs_mounts') else [],
                "docker_img": job['docker_img'],
                "experiment": job['experiment'],
                "job_id": job['job_id'],
                "max_restart_count": job['max_restart_count'],
                "restart_count": job['restart_count'],
                "status": job['status']
            }
        })
    return job_list


def job_exists(job_id):
    """Check if the job exists in the DB.

    :param job_id: UUID which identifies the job.
    :returns: Boolean representing if the job exists.
    """
    return job_id in JOB_DB


def retrieve_job_logs(job_id):
    """Retrieve job's logs.

    :param job_id: UUID which identifies the job.
    :returns: Job's logs.
    """
    return JOB_DB[job_id].get('log')


@app.route('/jobs', methods=['GET'])
def get_jobs():  # noqa
    r"""Get all active jobs.

    ---
    get:
      summary: Returns list of all active jobs.
      description: >-
        This resource is not expecting parameters and it will return a list
        representing all active jobs in JSON format.
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
                    "cvmfs_mounts": [
                      "atlas-condb",
                      "atlas"
                    ],
                    "docker_img": "busybox",
                    "experiment": "atlas",
                    "job_id": "1612a779-f3fa-4344-8819-3d12fa9b9d90",
                    "max_restart_count": 3,
                    "restart_count": 0,
                    "status": "succeeded"
                  },
                  "2e4bbc1d-db5e-4ee0-9701-6e2b1ba55c20": {
                    "cmd": "date",
                    "cvmfs_mounts": [
                      "atlas-condb",
                      "atlas"
                    ],
                    "docker_img": "busybox",
                    "experiment": "atlas",
                    "job_id": "2e4bbc1d-db5e-4ee0-9701-6e2b1ba55c20",
                    "max_restart_count": 3,
                    "restart_count": 0,
                    "status": "started"
                  }
                }
              }
    """
    # FIXME do Marshmallow validation after fixing the structure
    # of job list. Now it has the ID as key, it should be a plain
    # list of jobs so it can be validated with Marshmallow.

    return jsonify({"jobs": retrieve_all_jobs()}), 200


@app.route('/jobs', methods=['POST'])
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
        return jsonify({'message': 'Empty request'}), 400

    # Validate and deserialize input
    job_request, errors = job_request_schema.load(json_data)

    if errors:
        return jsonify(errors), 400

    job_parameters = dict(job_id=str(job_request['job_id']),
                          docker_img=job_request['docker_img'],
                          cmd=job_request['cmd'],
                          cvmfs_repos=job_request['cvmfs_mounts'],
                          env_vars=job_request['env_vars'],
                          namespace=job_request['experiment'],
                          shared_file_system=job_request['shared_file_system'],
                          job_type=job_request.get('job_type'))
    job_obj = instantiate_job(**job_parameters)
    if job_obj:
        job = copy.deepcopy(job_request)
        job['status'] = 'started'
        job['restart_count'] = 0
        job['max_restart_count'] = 3
        job['deleted'] = False
        job['obj'] = job_obj
        JOB_DB[str(job['job_id'])] = job

        job_db_entry = JobTable(
            id_=job['job_id'],
            workflow_uuid=job_request['workflow_uuid'],
            status=job['status'],
            job_type=job_request.get('job_type'),
            cvmfs_mounts=job_request['cvmfs_mounts'],
            shared_file_system=job_request['shared_file_system'],
            docker_img=job_request['docker_img'],
            experiment=job_request['experiment'],
            cmd=job_request['cmd'],
            env_vars=json.dumps(job_request['env_vars']),
            restart_count=job['restart_count'],
            max_restart_count=job['max_restart_count'],
            deleted=job['deleted'])
        Session.add(job_db_entry)
        Session.commit()
        return jsonify({'job_id': job['job_id']}), 201
    else:
        return jsonify({'job': 'Could not be allocated'}), 500


@app.route('/jobs/<job_id>', methods=['GET'])
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
                "cvmfs_mounts": [
                  "atlas-condb",
                  "atlas"
                ],
                "docker_img": "busybox",
                "experiment": "atlas",
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
        return jsonify({'message': 'The job {} doesn\'t exist'
                                   .format(job_id)}), 400


@app.route('/jobs/<job_id>/logs', methods=['GET'])
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
        return jsonify({'message': 'The job {} doesn\'t exist'
                        .format(job_id)}), 400


@app.route('/apispec', methods=['GET'])
def get_openapi_spec():
    """Get OpenAPI Spec.

    FIXME add openapi spec
    """
    return jsonify(app.config['OPENAPI_SPEC'])


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(threadName)s - %(levelname)s: %(message)s'
    )

    app.config.from_object('config')

    with app.app_context():
        app.config['OPENAPI_SPEC'] = build_openapi_spec()
        app.config['KUBERNETES_CLIENT'] = create_api_client()

    job_event_reader_thread = threading.Thread(target=watch_jobs,
                                               args=(JOB_DB,))

    job_event_reader_thread.start()

    app.run(debug=True, port=5000,
            host='0.0.0.0')
