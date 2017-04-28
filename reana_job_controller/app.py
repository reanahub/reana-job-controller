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
import logging
import threading
import uuid

from flask import Flask, abort, jsonify, request
from reana_job_controller.k8s import (create_api_client, instantiate_job,
                                      watch_jobs, watch_pods)
from reana_job_controller.schemas import Job, JobRequest
from reana_job_controller.spec import build_openapi_spec

app = Flask(__name__)
app.secret_key = "mega secret key"
JOB_DB = {}

job_request_schema = JobRequest()
job_schema = Job()


def filter_jobs(job_db):
    """Filter unsolicited job_db fields.

    :param job_db: Dictionary which contains all jobs.
    :returns: A copy of `job_db` without `obj`, `deleted` and `pod`
        fields.
    """
    job_db_copy = copy.deepcopy(job_db)
    for job_name in job_db_copy:
        del(job_db_copy[job_name]['obj'])
        del(job_db_copy[job_name]['deleted'])
        if job_db_copy[job_name].get('pod'):
            del(job_db_copy[job_name]['pod'])

    return job_db_copy


@app.route('/jobs', methods=['GET'])
def get_jobs():  # noqa
    """Get all jobs.

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
                    "cmd": "sleep 1000",
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
                    "cmd": "sleep 1000",
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

    return jsonify({"jobs": filter_jobs(JOB_DB)}), 200


@app.route('/jobs', methods=['POST'])
def create_job():  # noqa
    """Create a new job.

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

    job_obj = instantiate_job(job_request['job_id'],
                              job_request['docker_img'],
                              job_request['cmd'],
                              job_request['cvmfs_mounts'],
                              job_request['env_vars'],
                              job_request['experiment'],
                              job_request['shared_file_system'])

    if job_obj:
        job = copy.deepcopy(job_request)
        job['status'] = 'started'
        job['restart_count'] = 0
        job['max_restart_count'] = 3
        job['obj'] = job_obj
        job['deleted'] = False
        JOB_DB[job['job_id']] = job
        return jsonify({'job_id': job['job_id']}), 201
    else:
        return jsonify({'job': 'Could not be allocated'}), 500


@app.route('/jobs/<job_id>', methods=['GET'])
def get_job(job_id):  # noqa
    """Get a Job.

    ---
    get:
      summary: Returns details about a given job.
      description: >-
        This resource is expecting the job's UUID as a path parameter. Its
        information will be served in JSON format.
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
                "cmd": "sleep 1000",
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
    """

    if job_id in JOB_DB:
        job_copy = copy.deepcopy(JOB_DB[job_id])
        del(job_copy['obj'])
        del(job_copy['deleted'])
        if job_copy.get('pod'):
            del(job_copy['pod'])

        # FIXME job_schema.dump(job_copy) no time now to test
        # since it needs to be run inside the cluster
        return jsonify({'job': job_copy}), 200
    else:
        return jsonify({'message': 'The job {} doesn\'t exist'.
                                   format(job_id)}), 400


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

    job_event_reader_thread = threading.Thread(target=watch_jobs,
                                               args=(JOB_DB,
                                                     app.config['PYKUBE_API']))

    job_event_reader_thread.start()
    pod_event_reader_thread = threading.Thread(target=watch_pods,
                                               args=(JOB_DB,
                                                     app.config['PYKUBE_API']))
    with app.app_context():
        app.config['OPENAPI_SPEC'] = build_openapi_spec()
        app.config['PYKUBE_CLIENT'] = create_api_client(
            app.config['PYKUBE_API'])

    pod_event_reader_thread.start()

    app.run(debug=True, port=5000,
            host='0.0.0.0')
