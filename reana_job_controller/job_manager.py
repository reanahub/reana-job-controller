# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Job Manager."""

import json
import shlex

from reana_commons.utils import calculate_file_access_time
from reana_db.database import Session
from reana_db.models import Job as JobTable
from reana_db.models import JobCache, JobStatus, Workflow

from reana_job_controller.config import MAX_JOB_RESTARTS


class JobManager():
    """Job management interface."""

    def __init__(self, docker_img='', cmd=[], env_vars={}, job_id=None,
                 workflow_uuid=None):
        """Instanciates basic job.

        :param docker_img: Docker image.
        :type docker_img: str
        :param cmd: Command to execute.
        :type cmd: list
        :param env_vars: Environment variables.
        :type env_vars: dict
        :param job_id: Unique job id.
        :type job_id: str
        :param workflow_id: Unique workflow id.
        :type workflow_id: str
        """
        self.docker_img = docker_img or ''
        if isinstance(cmd, str):
            self.cmd = shlex.split(cmd)
        else:
            self.cmd = cmd or []
        self.env_vars = env_vars or {}
        self.job_id = job_id
        self.workflow_uuid = workflow_uuid

    def execution_hook(fn):
        """Add before execution hooks and DB operations."""
        def wrapper(inst, *args, **kwargs):
            inst.before_execution()
            backend_job_id = fn(inst, *args, **kwargs)
            inst.create_job_in_db(backend_job_id)
            inst.cache_job()
            return backend_job_id
        return wrapper

    def before_execution(self):
        """Before job submission hook."""
        pass

    def after_execution(self):
        """After job submission hook."""
        pass

    @execution_hook
    def execute(self):
        """Execute a job.

        :returns: Job ID.
        :rtype: str
        """
        raise NotImplementedError

    def get_status(self):
        """Get job status.

        :returns: job status.
        :rtype: str
        """
        raise NotImplementedError

    def get_logs(self):
        """Get job log.

        :returns: stderr, stdout of a job.
        :rtype: dict
        """
        raise NotImplementedError

    def stop(self):
        """Stop a job."""
        raise NotImplementedError

    def create_job_in_db(self, backend_job_id):
        """Create job in db."""
        job_db_entry = JobTable(
            backend_job_id=backend_job_id,
            workflow_uuid=self.workflow_uuid,
            status=JobStatus.created.name,
            backend=self.backend,
            cvmfs_mounts=self.cvmfs_mounts or '',
            shared_file_system=self.shared_file_system or False,
            docker_img=self.docker_img,
            cmd=json.dumps(self.cmd),
            env_vars=json.dumps(self.env_vars),
            restart_count=0,
            max_restart_count=MAX_JOB_RESTARTS,
            deleted=False,
            name=self.job_id,
            prettified_cmd=json.dumps(self.cmd))
        Session.add(job_db_entry)
        Session.commit()
        self.job_id = str(job_db_entry.id_)

    def cache_job(self):
        """Cache a job."""
        workflow = Session.query(Workflow).filter_by(
            id_=self.workflow_uuid).one_or_none()
        access_times = calculate_file_access_time(workflow.get_workspace())
        prepared_job_cache = JobCache()
        prepared_job_cache.job_id = self.job_id
        prepared_job_cache.access_times = access_times
        Session.add(prepared_job_cache)
        Session.commit()

    def update_job_status(self):
        """Update job status in DB."""
        pass
