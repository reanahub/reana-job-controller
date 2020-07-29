.. include:: ../README.rst
   :end-before: About

.. include:: ../README.rst
   :start-after: =====
   :end-before: Features

Features:

.. include:: ../README.rst
   :start-line: 32
   :end-before: Useful links

API
===

Compute backends
----------------

REANA-Job-Controller offers an abstract interface to submit jobs to different
compute backends.

.. automodule:: reana_job_controller.job_manager
   :members:

.. image:: /_static/reana-job-manager.png


Kubernetes
~~~~~~~~~~

.. automodule:: reana_job_controller.kubernetes_job_manager
   :members:

.. note::
   REANA-Job-Controller supports the Kubernetes job manager by default, no need
   to pass any build argument.

HTCondor
~~~~~~~~

.. automodule:: reana_job_controller.htcondorcern_job_manager
   :members:

.. note::
   To build REANA-Job-Controller Docker image with HTCondor dependencies use build
   argument ``COMPUTE_BACKENDS=kubernetes,htcondorcern``.

   .. code-block:: console

      $ reana-dev docker-build -c reana-job-controller \
        -b COMPUTE_BACKENDS=kubernetes,htcondorcern

Slurm
~~~~~

.. automodule:: reana_job_controller.slurmcern_job_manager
   :members:

.. note::
   To build REANA-Job-Controller Docker image with Slum dependencies use build
   argument ``COMPUTE_BACKENDS=kubernetes,slurmcern``.

   .. code-block:: console

      $ reana-dev docker-build -c reana-job-controller \
        -b COMPUTE_BACKENDS=kubernetes,slurmcern

.. note::
   Please note that CERN Slurm cluster access is not granted by
   `default <https://batchdocs.web.cern.ch/linuxhpc/access.html>`_.

REST API
========

The REANA Job Controller API offers different endpoints to create, manage and monitor jobs.
Detailed REST API documentation can be found `here <_static/api.html>`_.

.. automodule:: reana_job_controller.rest
   :members:
   :exclude-members: get_openapi_spec

.. include:: ../CHANGES.rst

.. include:: ../CONTRIBUTING.rst

License
=======

.. include:: ../LICENSE

In applying this license, CERN does not waive the privileges and immunities
granted to it by virtue of its status as an Intergovernmental Organization or
submit itself to any jurisdiction.

.. include:: ../AUTHORS.rst

