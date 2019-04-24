.. _developerguide:

Developer guide
===============

This developer guide is meant for software developers who would like to
understand REANA-Job-Controller source code and contribute to it.

Job backends
------------

REANA-Job-Controller offers an abstract interface to submit jobs to different
compute backends. Currently it is only implemented for Kubernetes.

.. automodule:: reana_job_controller.job_manager
   :members:

.. image:: /_static/reana-job-manager.png

Kubernetes
~~~~~~~~~~

Kubernetes jobs management is done via ``KubernetesJobManager`` class which
implements the previously mentioned ``JobManager`` interface.

Execute method creates Kubernetes job specification and submits it. This
method uses ``@JobManager.execution_hook`` decorator to execute specific
operations defined in before_execution and necessary DB transactions in the
right order.

Stop static function is responsible for stoping/deleting successfully finished
or failed jobs.
