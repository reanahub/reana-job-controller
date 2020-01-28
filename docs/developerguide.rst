.. _developerguide:

Developer guide
===============

This developer guide is meant for software developers who would like to
understand REANA-Job-Controller source code and contribute to it.

Compute backends
----------------

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
argument ``COMPUTE_BACKENDS=kubernetes,htcondorcern``.

.. code-block:: console

    $ reana-dev docker-build -c reana-job-controller -b COMPUTE_BACKENDS=kubernetes,htcondorcern

The users should then upload their CERN username and keytab secrets using:

.. code-block:: console

    $ reana-client secrets-add --env CERN_USER=johndoe
                               --env CERN_KEYTAB=.keytab
                               --file ~/.keytab

see the `reana-client's documentation on secrets <https://reana-client.readthedocs.io/en/latest/userguide.html#adding-secrets>`_.

The users will then be able to specify compute backend ``htcondorcern`` in their
workflow specification files to provide hints to the workflow execution system
to run certain workflow steps on the HTCondorCERN backend. How this is done
concretely depends on the specific workflow engine (CWL, Serial, Yadage).

Slurm
~~~~~

To build REANA-Job-Controller Docker image with Slum dependencies use build
argument ``COMPUTE_BACKENDS=kubernetes,slurmcern``.


.. code-block:: console

    $ reana-dev docker-build -c reana-job-controller -b COMPUTE_BACKENDS=kubernetes,slurmcern

The users should then upload their CERN username and keytab secrets using:

.. code-block:: console

    $ reana-client secrets-add --env CERN_USER=johndoe
                               --env CERN_KEYTAB=.keytab
                               --file ~/.keytab


.. note::
   Please note that CERN Slurm cluster access is not granted by
   `default <https://batchdocs.web.cern.ch/linuxhpc/access.html>`_.

Once the user has an access will then be able to specify compute backend
``slurmcern`` in their workflow specification files to provide hints to the
workflow execution system to run certain workflow steps on the SlurmCern backend.
How this is done concretely depends on the specific workflow engine
(CWL, Serial, Yadage).
