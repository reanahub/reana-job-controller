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

import k8s
from flask import Flask, abort, jsonify, request

app = Flask(__name__)
app.secret_key = "mega secret key"
JOB_DB = {}


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
def get_jobs():
    """Get all jobs.

    .. http:get:: /jobs

        Returns a JSON list with all the jobs.

        **Request**:

        .. sourcecode:: http

            GET /jobs HTTP/1.1
            Content-Type: application/json
            Host: localhost:5000

        :reqheader Content-Type: application/json

        **Responses**:

        .. sourcecode:: http

            HTTP/1.0 200 OK
            Content-Length: 80
            Content-Type: application/json

            {
              "jobs": {
                "1612a779-f3fa-4344-8819-3d12fa9b9d90": {
                  "cmd": "sleep 1000",
                  "cvmfs_mounts": [
                    "atlas-condb",
                    "atlas"
                  ],
                  "docker-img": "busybox",
                  "experiment": "atlas",
                  "job-id": "1612a779-f3fa-4344-8819-3d12fa9b9d90",
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
                  "docker-img": "busybox",
                  "experiment": "atlas",
                  "job-id": "2e4bbc1d-db5e-4ee0-9701-6e2b1ba55c20",
                  "max_restart_count": 3,
                  "restart_count": 0,
                  "status": "started"
                }
              }
            }

        :resheader Content-Type: application/json
        :statuscode 200: no error - the list has been returned.
    """
    return jsonify({"jobs": filter_jobs(JOB_DB)}), 200


@app.route('/jobs', methods=['POST'])
def create_job():
    """Create a new job.

    .. http:post:: /jobs

        This resource is expecting JSON data with all the necessary
        information of a new job.

        **Request**:

        .. sourcecode:: http

            POST /jobs HTTP/1.1
            Content-Type: application/json
            Host: localhost:5000

            {
                "docker-img": "busybox",
                "cmd": "sleep 1000",
                "cvmfs_mounts": ['atlas-condb', 'atlas'],
                "env-vars": {"DATA": "/data"},
                "experiment": "atlas"
            }

        :reqheader Content-Type: application/json
        :json body: JSON with the information of the job.

        **Responses**:

        .. sourcecode:: http

            HTTP/1.0 200 OK
            Content-Length: 80
            Content-Type: application/json

            {
              "job-id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac"
            }

        :resheader Content-Type: application/json
        :statuscode 201: no error - the job was created
        :statuscode 400: invalid request - problably a malformed JSON
        :statuscode 500: internal error - probably the job could not be
            created
    """
    if not request.json \
       or not ('experiment') in request.json\
       or not ('docker-img' in request.json):
        print(request.json)
        abort(400)

    cmd = request.json['cmd'] if 'cmd' in request.json else None
    env_vars = (request.json['env-vars']
                if 'env-vars' in request.json else {})

    if request.json.get('cvmfs_mounts'):
        cvmfs_repos = request.json.get('cvmfs_mounts')
    else:
        cvmfs_repos = []

    job_id = str(uuid.uuid4())

    job_obj = k8s.create_job(job_id,
                             request.json['docker-img'],
                             cmd,
                             cvmfs_repos,
                             env_vars,
                             request.json['experiment'],
                             shared_file_system=True)

    if job_obj:
        job = copy.deepcopy(request.json)
        job['job-id'] = job_id
        job['status'] = 'started'
        job['restart_count'] = 0
        job['max_restart_count'] = 3
        job['obj'] = job_obj
        job['deleted'] = False
        JOB_DB[job_id] = job
        return jsonify({'job-id': job_id}), 201
    else:
        return jsonify({'job': 'Could not be allocated'}), 500


@app.route('/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """Get a job.

    FIXME --> probably this endpoint should be merged with `get_jobs()`

    .. http:get:: /jobs

        Returns a JSON list with all the jobs.

        **Request**:

        .. sourcecode:: http

            GET /jobs HTTP/1.1
            Content-Type: application/json
            Host: localhost:5000

        :reqheader Content-Type: application/json

        **Responses**:

        .. sourcecode:: http

            HTTP/1.0 200 OK
            Content-Length: 80
            Content-Type: application/json

            {
              "job": {
                "cmd": "sleep 1000",
                "cvmfs_mounts": [
                  "atlas-condb",
                  "atlas"
                ],
                "docker-img": "busybox",
                "experiment": "atlas",
                "job-id": "cdcf48b1-c2f3-4693-8230-b066e088c6ac",
                "max_restart_count": 3,
                "restart_count": 0,
                "status": "started"
              }
            }

        :resheader Content-Type: application/json
        :statuscode 200: no error - the list has been returned.
        :statuscode 404: error - the specified job doesn't exist.
    """
    if job_id in JOB_DB:
        job_copy = copy.deepcopy(JOB_DB[job_id])
        del(job_copy['obj'])
        del(job_copy['deleted'])
        if job_copy.get('pod'):
            del(job_copy['pod'])
        return jsonify({'job': job_copy}), 200
    else:
        abort(404)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(threadName)s - %(levelname)s: %(message)s'
    )
    job_event_reader_thread = threading.Thread(target=k8s.watch_jobs,
                                               args=(JOB_DB,))
    job_event_reader_thread.start()
    pod_event_reader_thread = threading.Thread(target=k8s.watch_pods,
                                               args=(JOB_DB,))
    pod_event_reader_thread.start()
    app.run(debug=True, port=5000,
            host='0.0.0.0')
