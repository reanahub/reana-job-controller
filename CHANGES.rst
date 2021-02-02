Changes
=======

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
