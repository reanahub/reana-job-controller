.. _developerguide:

Developer guide
===============

This developer guide is meant for software developers who would like to
understand REANA-Job-Controller source code and contribute to it.

Compute backends
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

HTCondor
~~~~~~~~

To build REANA-Job-Controller Docker image with HTCondor dependencies use build
argument ``HTCONDORCERN=1``.

.. code-block:: console

    $ reana-dev docker-build -c reana-job-controller -b HTCONDORCERN=1

The users should then upload their HTCondor username and keytab secrets using:

.. code-block:: console

    $ reana-client secrets-add --env HTCONDORCERN_USERNAME=johndoe
                               --env HTCONDORCERN_KEYTAB=.keytab
                               --file ~/.keytab

see the `reana-client's documentation on secrets <https://reana-client.readthedocs.io/en/latest/userguide.html#adding-secrets>`_.

The users will then be able to specify compute backend ``htcondorcern`` in their
workflow specification files to provide hints to the workflow execution system
to run certain workflow steps on the HTCondorCERN backend. How this is done
concretely depends on the specific workflow engine (CWL, Serial, Yadage).
