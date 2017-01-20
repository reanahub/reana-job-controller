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
    job_db_copy = copy.deepcopy(job_db)
    for job_name in job_db_copy:
        del(job_db_copy[job_name]['obj'])
        del(job_db_copy[job_name]['deleted'])
        if job_db_copy[job_name].get('pod'):
            del(job_db_copy[job_name]['pod'])

    return job_db_copy


@app.route('/api/v1.0/jobs', methods=['GET'])
def get_jobs():
    return jsonify({"jobs": filter_jobs(JOB_DB)}), 200


@app.route('/api/v1.0/k8sjobs', methods=['GET'])
def get_k8sjobs():
    return jsonify({"jobs": k8s.get_jobs()}), 200


@app.route('/api/v1.0/jobs', methods=['POST'])
def create_job():
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


@app.route('/api/v1.0/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
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
