.. _developerguide:

Developer guide
===============

This developer guide is meant for software developers who would like to
understand REANA-Job-Controller source code and contribute to it.

Job backends
------------

.. image:: /_static/reana-job-manager.png

Kubernetes
==========

Kubernetes jobs management is done via KubernetesJobManager class which
inherits main job management class - JobManager.

Execute method creates Kubernetes job specification and submits it. This
method uses ``@JobManager.execution_hook`` decorator to execute specific
operations defined in before_execution and necessary DB transactions in the
right order.

Stop static function is responsible for stoping/deleting successfully finished
or failed job.
