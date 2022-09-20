Changes
=======

Version 0.9.0 (UNRELEASED)
--------------------------

- Adds support for Rucio
- Adds support for specifying ``slurm_partition`` and ``slurm_time`` for Slurm compute backend jobs.
- Changes ``reana-auth-vomsproxy`` sidecar to the latest stable version to support client-side proxy file generation technique and ESCAPE VOMS.
- Changes default Slurm partition to ``inf-short``.
- Changes to PostgreSQL 12.10.

Version 0.8.1 (2022-02-07)
---------------------------

- Adds support for specifying ``kubernetes_job_timeout`` for Kubernetes compute backend jobs.
- Adds a new condition to allow processing jobs in case of receiving multiple failed events when job containers are not in a running state.

Version 0.8.0 (2021-11-22)
--------------------------

- Adds database connection closure after each REST API request.
- Adds labels to job and run-batch pods to reduce k8s events to listen to for ``job-monitor``.
- Fixes auto-mounting of Kubernetes API token inside user jobs by disabling it.
- Changes job dispatching to use only job-specific node labels.
- Changes to PostgreSQL 12.8.

Version 0.7.5 (2021-07-05)
--------------------------

- Changes HTCondor to 8.9.11.
- Changes myschedd package and configuration to latest versions.
- Fixes job command formatting bug for CWL workflows on HTCondor.

Version 0.7.4 (2021-04-28)
--------------------------

- Adds configuration environment variable to set job memory limits for the Kubernetes compute backend (``REANA_KUBERNETES_JOBS_MEMORY_LIMIT``).
- Fixes Kubernetes job log capture to include information about failures caused by external factors such as OOMKilled.
- Adds support for specifying ``kubernetes_memory_limit`` for Kubernetes compute backend jobs.

Version 0.7.3 (2021-03-17)
--------------------------

- Adds new configuration to toggle Kubernetes user jobs clean up.
- Fixes HTCondor Docker networking and machine version requirement setup.
- Fixes HTCondor logs and workspace files retrieval on job failure.
- Fixes Slurm job submission providing the correct shell environment to run Singularity.
- Changes HTCondor myschedd to the latest version.
- Changes job status ``succeeded`` to ``finished`` to use central REANA nomenclature.
- Changes how to deserialise job commands using central REANA-Commons deserialiser function.

Version 0.7.2 (2021-02-03)
--------------------------

- Fixes minor code warnings.
- Changes CI system to include Python flake8 and Dockerfile hadolint checkers.

Version 0.7.1 (2020-11-10)
--------------------------

- Adds support for specifying ``htcondor_max_runtime`` and ``htcondor_accounting_group`` for HTCondor compute backend jobs.
- Fixes Docker build by properly exiting when there are problems with ``myschedd`` installation.

Version 0.7.0 (2020-10-20)
--------------------------

- Adds support for running unpacked Docker images from CVMFS on HTCondor jobs.
- Adds support for pulling private images using image pull secrets.
- Adds support for VOMS proxy as a new authentication method.
- Adds pinning of all Python dependencies allowing to easily rebuild component images at later times.
- Fixes HTCondor job submission retry technique.
- Changes error reporting on Docker image related failures.
- Changes runtime pods to prefix user workflows with the configured REANA prefix.
- Changes CVMFS to be read-only mount.
- Changes runtime job instantiation into the configured runtime namespace.
- Changes test suite to enable running tests locally also on macOS platform.
- Changes CERN HTCondor compute backend to use the new ``myschedd`` connection library.
- Changes CERN Slurm compute backend to improve job status detection.
- Changes base image to use Python 3.8.
- Changes code formatting to respect ``black`` coding style.
- Changes documentation to single-page layout.

Version 0.6.1 (2020-05-25)
--------------------------

- Upgrades REANA-Commons package using latest Kubernetes Python client version.

Version 0.6.0 (2019-12-20)
--------------------------

- Adds generic job manager class and provides example classes for CERN HTCondor
  and CERN Slurm clusters.
- Moves job controller to the same Kubernetes pod with the
  REANA-Workflow-Engine-* (sidecar pattern).
- Adds sidecar container to the Kubernetes job pod if Kerberos authentication
  is required.
- Provides user secrets to the job container runtime tasks.
- Refactors job monitoring using singleton pattern.

Version 0.5.1 (2019-04-23)
--------------------------

- Pins ``urllib3`` due to a conflict while installing ``Kubernetes`` Python
  library.
- Fixes documenation build badge.

Version 0.5.0 (2019-04-23)
--------------------------

- Adds a new endpoint to delete jobs (Kubernetes).
- Introduces new common interface for job management which defines what the
  compute backends should offer to be compatible with REANA, currently only
  Kubernetes backend is supported.
- Fixes security vulnerability which allowed users to access other people's
  workspaces.
- Makes CVMFS mounts optional and configurable at repository level.
- Updates the creation of CVMFS volumes specification, it now uses normal
  persistent volume claims.
- Increases stability and improves test coverage.

Version 0.4.0 (2018-11-06)
--------------------------

- Improves REST API documentation rendering.
- Changes license to MIT.

Version 0.3.2 (2018-09-26)
--------------------------

- Adapts Kubernetes API adaptor to mount shared volumes on jobs as CEPH
  ``persistentVolumeClaim``'s (managed by ``reana-cluster``) instead of plain
  CEPH volumes.

Version 0.3.1 (2018-09-07)
--------------------------

- Pins REANA-Commons and REANA-DB dependencies.

Version 0.3.0 (2018-08-10)
--------------------------

- Adds uwsgi for production deployments.
- Switches from pykube to official Kubernetes python client.
- Adds compatibility with latest Kubernetes.


Version 0.2.0 (2018-04-19)
--------------------------

- Adds dockerignore file to ease developments.

Version 0.1.0 (2018-01-30)
--------------------------

- Initial public release.

.. admonition:: Please beware

   Please note that REANA is in an early alpha stage of its development. The
   developer preview releases are meant for early adopters and testers. Please
   don't rely on released versions for any production purposes yet.
