# Changelog

## [0.9.5](https://github.com/reanahub/reana-job-controller/compare/0.9.4...0.9.5) (2025-03-06)


### Bug fixes

* **config:** update reana-auth-vomsproxy to 1.3.1 to fix WLCG IAM ([#481](https://github.com/reanahub/reana-job-controller/issues/481)) ([48c362f](https://github.com/reanahub/reana-job-controller/commit/48c362fc975d9ee0e18af2f4fcd5ede6ed923134))

## [0.9.4](https://github.com/reanahub/reana-job-controller/compare/0.9.3...0.9.4) (2024-11-29)


### Build

* **deps:** update reana-auth-vomsproxy to 1.3.0 ([#466](https://github.com/reanahub/reana-job-controller/issues/466)) ([72e9ea1](https://github.com/reanahub/reana-job-controller/commit/72e9ea1442d2b6cf7d466d0701e269fda1e15b22))
* **docker:** pin setuptools 70 ([#465](https://github.com/reanahub/reana-job-controller/issues/465)) ([c593d9b](https://github.com/reanahub/reana-job-controller/commit/c593d9bc84763f142573396be48c762eefa8f6ec))
* **python:** bump shared REANA packages as of 2024-11-28 ([#477](https://github.com/reanahub/reana-job-controller/issues/477)) ([9cdd06c](https://github.com/reanahub/reana-job-controller/commit/9cdd06c72faa5ded628b2766113ab37ac06f5868))


### Features

* **backends:** add new Compute4PUNCH backend ([#430](https://github.com/reanahub/reana-job-controller/issues/430)) ([4243252](https://github.com/reanahub/reana-job-controller/commit/42432522c8d9dd5e4ee908a16b1be87046908e08))


### Bug fixes

* **config:** read secret key from env ([#476](https://github.com/reanahub/reana-job-controller/issues/476)) ([1b5aa98](https://github.com/reanahub/reana-job-controller/commit/1b5aa98b0ed76ea614dac1209ba23b366d417d9f))
* **config:** update reana-auth-vomsproxy to 1.2.1 to fix WLCG IAM ([#457](https://github.com/reanahub/reana-job-controller/issues/457)) ([132868f](https://github.com/reanahub/reana-job-controller/commit/132868f4824a0f4049febf17c90bea0df838e724))
* **htcondorcern:** run provided command in unpacked image ([#474](https://github.com/reanahub/reana-job-controller/issues/474)) ([9cda591](https://github.com/reanahub/reana-job-controller/commit/9cda591affaa1f821409961ec4e379e1bf5fa248)), closes [#471](https://github.com/reanahub/reana-job-controller/issues/471)
* **htcondorcern:** support multiline commands ([#474](https://github.com/reanahub/reana-job-controller/issues/474)) ([eb07aa9](https://github.com/reanahub/reana-job-controller/commit/eb07aa9b7b03d38dd47cd004ff8b48440ad45c2a)), closes [#470](https://github.com/reanahub/reana-job-controller/issues/470)
* **kubernetes:** avoid privilege escalation in Kubernetes jobs ([#476](https://github.com/reanahub/reana-job-controller/issues/476)) ([389f0ea](https://github.com/reanahub/reana-job-controller/commit/389f0ea9606d4ac5fa24458b7cef39e8ab430c64))

## [0.9.3](https://github.com/reanahub/reana-job-controller/compare/0.9.2...0.9.3) (2024-03-04)


### Build

* **certificates:** update expired CERN Grid CA certificate ([#440](https://github.com/reanahub/reana-job-controller/issues/440)) ([8d6539a](https://github.com/reanahub/reana-job-controller/commit/8d6539a94af035aca1191c9a6a7ff43791a3c930)), closes [#439](https://github.com/reanahub/reana-job-controller/issues/439)
* **docker:** non-editable submodules in "latest" mode ([#416](https://github.com/reanahub/reana-job-controller/issues/416)) ([3bdda63](https://github.com/reanahub/reana-job-controller/commit/3bdda6367d9a4682028a2a7df7268e4c9b42ef6c))
* **python:** bump all required packages as of 2024-03-04 ([#442](https://github.com/reanahub/reana-job-controller/issues/442)) ([de119eb](https://github.com/reanahub/reana-job-controller/commit/de119eb8f663dcfe1a126747a7c404e39ece47c0))
* **python:** bump shared REANA packages as of 2024-03-04 ([#442](https://github.com/reanahub/reana-job-controller/issues/442)) ([fc77628](https://github.com/reanahub/reana-job-controller/commit/fc776284abe15030581d5adf4aa575f4f3a1c756))


### Features

* **shutdown:** stop all running jobs before stopping workflow ([#423](https://github.com/reanahub/reana-job-controller/issues/423)) ([866675b](https://github.com/reanahub/reana-job-controller/commit/866675b7288e840130cfee851f4a248a9ae2617d))


### Bug fixes

* **database:** limit the number of open database connections ([#437](https://github.com/reanahub/reana-job-controller/issues/437)) ([980f749](https://github.com/reanahub/reana-job-controller/commit/980f74982b75176c5958f09bc581e941cdf44310))


### Performance improvements

* **cache:** avoid caching jobs when the cache is disabled ([#435](https://github.com/reanahub/reana-job-controller/issues/435)) ([553468f](https://github.com/reanahub/reana-job-controller/commit/553468f55f6b63cebba45ccd460593131e5dcfea)), closes [#422](https://github.com/reanahub/reana-job-controller/issues/422)


### Code refactoring

* **db:** set job status also in the main database ([#423](https://github.com/reanahub/reana-job-controller/issues/423)) ([9d6fc99](https://github.com/reanahub/reana-job-controller/commit/9d6fc99063deb468fe9d45d9ad626c745c7bd827))
* **docs:** move from reST to Markdown ([#428](https://github.com/reanahub/reana-job-controller/issues/428)) ([4732884](https://github.com/reanahub/reana-job-controller/commit/4732884a3da52694fb86d72873eceef3ad2deb27))
* **monitor:** centralise logs and status updates ([#423](https://github.com/reanahub/reana-job-controller/issues/423)) ([3685b01](https://github.com/reanahub/reana-job-controller/commit/3685b01a57e1d0b1bd363534ff331b988e04719e))
* **monitor:** move fetching of logs to job-manager ([#423](https://github.com/reanahub/reana-job-controller/issues/423)) ([1fc117e](https://github.com/reanahub/reana-job-controller/commit/1fc117ebb3dd908a01ee3fd539fa24a07cdb4d16))


### Code style

* **black:** format with black v24 ([#426](https://github.com/reanahub/reana-job-controller/issues/426)) ([8a2757e](https://github.com/reanahub/reana-job-controller/commit/8a2757ee8bf52d1d5189f1dd1d690cb8922599cb))


### Continuous integration

* **commitlint:** addition of commit message linter ([#417](https://github.com/reanahub/reana-job-controller/issues/417)) ([f547d3b](https://github.com/reanahub/reana-job-controller/commit/f547d3bc25f438203252ea149cf6c6e5d2428189))
* **commitlint:** allow release commit style ([#443](https://github.com/reanahub/reana-job-controller/issues/443)) ([0fc9794](https://github.com/reanahub/reana-job-controller/commit/0fc9794bfbe2799bb9666ec5b2ff1dd15def8c34))
* **commitlint:** check for the presence of concrete PR number ([#425](https://github.com/reanahub/reana-job-controller/issues/425)) ([35bc1c5](https://github.com/reanahub/reana-job-controller/commit/35bc1c5acb1aa8ff51689142a007da66e49d8d2b))
* **pytest:** move to PostgreSQL 14.10 ([#429](https://github.com/reanahub/reana-job-controller/issues/429)) ([42622fa](https://github.com/reanahub/reana-job-controller/commit/42622fa1597e49fae36c625941188be5a093eda9))
* **release-please:** initial configuration ([#417](https://github.com/reanahub/reana-job-controller/issues/417)) ([fca6f74](https://github.com/reanahub/reana-job-controller/commit/fca6f74aa0d0e55e41d96b0e79c66a5cb3517189))
* **release-please:** update version in Dockerfile/OpenAPI specs ([#421](https://github.com/reanahub/reana-job-controller/issues/421)) ([e6742f2](https://github.com/reanahub/reana-job-controller/commit/e6742f2911df46dfbef3b7e9104330d58e2b4211))
* **shellcheck:** fix exit code propagation ([#425](https://github.com/reanahub/reana-job-controller/issues/425)) ([8e74a85](https://github.com/reanahub/reana-job-controller/commit/8e74a85c90df00c8734a6cdd81597f583d11d566))


### Documentation

* **authors:** complete list of contributors ([#434](https://github.com/reanahub/reana-job-controller/issues/434)) ([b9f8364](https://github.com/reanahub/reana-job-controller/commit/b9f83647fa8fc337140da5c3f2814ea24a15c5d5))

## 0.9.2 (2023-12-12)

- Adds metadata labels to Dockerfile.
- Adds automated multi-platform container image building for amd64 and arm64 architectures.
- Changes CVMFS support to allow users to automatically mount any available repository.
- Fixes container image building on the arm64 architecture.
- Fixes the creation of Kubernetes jobs by retrying in case of error and by correctly handling the error after reaching the retry limit.
- Fixes job monitoring in cases when job creation fails, for example when it is not possible to successfully mount volumes.

## 0.9.1 (2023-09-27)

- Adds unique error messages to Kubernetes job monitor to more easily identify source of problems.
- Changes Paramiko to version 3.0.0.
- Changes HTCondor to version 9.0.17 (LTS).
- Changes Rucio authentication helper to version 1.1.1 allowing users to override the Rucio server and authentication hosts independently of VO name.
- Fixes intermittent Slurm connection issues by DNS-resolving the Slurm head node IPv4 address before establishing connections.
- Fixes deletion of failed jobs not being performed when Kerberos is enabled.
- Fixes job monitoring to consider OOM-killed jobs as failed.
- Fixes Slurm command generation issues when using fully-qualified image names.
- Fixes location of HTCondor build dependencies.
- Fixes detection of default Rucio server and authentication host for ATLAS VO.
- Fixes container image names to be Podman-compatible.

## 0.9.0 (2023-01-20)

- Adds support for Rucio authentication for workflow jobs.
- Adds support for specifying `slurm_partition` and `slurm_time` for Slurm compute backend jobs.
- Adds Kerberos sidecar container to renew ticket periodically for long-running jobs.
- Changes `reana-auth-vomsproxy` sidecar to the latest stable version to support client-side proxy file generation technique and ESCAPE VOMS.
- Changes default Slurm partition to `inf-short`.
- Changes to PostgreSQL 12.13.
- Changes the base image of the component to Ubuntu 20.04 LTS and reduces final Docker image size by removing build-time dependencies.

## 0.8.1 (2022-02-07)

- Adds support for specifying `kubernetes_job_timeout` for Kubernetes compute backend jobs.
- Adds a new condition to allow processing jobs in case of receiving multiple failed events when job containers are not in a running state.

## 0.8.0 (2021-11-22)

- Adds database connection closure after each REST API request.
- Adds labels to job and run-batch pods to reduce k8s events to listen to for `job-monitor`.
- Fixes auto-mounting of Kubernetes API token inside user jobs by disabling it.
- Changes job dispatching to use only job-specific node labels.
- Changes to PostgreSQL 12.8.

## 0.7.5 (2021-07-05)

- Changes HTCondor to 8.9.11.
- Changes myschedd package and configuration to latest versions.
- Fixes job command formatting bug for CWL workflows on HTCondor.

## 0.7.4 (2021-04-28)

- Adds configuration environment variable to set job memory limits for the Kubernetes compute backend (`REANA_KUBERNETES_JOBS_MEMORY_LIMIT`).
- Fixes Kubernetes job log capture to include information about failures caused by external factors such as OOMKilled.
- Adds support for specifying `kubernetes_memory_limit` for Kubernetes compute backend jobs.

## 0.7.3 (2021-03-17)

- Adds new configuration to toggle Kubernetes user jobs clean up.
- Fixes HTCondor Docker networking and machine version requirement setup.
- Fixes HTCondor logs and workspace files retrieval on job failure.
- Fixes Slurm job submission providing the correct shell environment to run Singularity.
- Changes HTCondor myschedd to the latest version.
- Changes job status `succeeded` to `finished` to use central REANA nomenclature.
- Changes how to deserialise job commands using central REANA-Commons deserialiser function.

## 0.7.2 (2021-02-03)

- Fixes minor code warnings.
- Changes CI system to include Python flake8 and Dockerfile hadolint checkers.

## 0.7.1 (2020-11-10)

- Adds support for specifying `htcondor_max_runtime` and `htcondor_accounting_group` for HTCondor compute backend jobs.
- Fixes Docker build by properly exiting when there are problems with `myschedd` installation.

## 0.7.0 (2020-10-20)

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
- Changes CERN HTCondor compute backend to use the new `myschedd` connection library.
- Changes CERN Slurm compute backend to improve job status detection.
- Changes base image to use Python 3.8.
- Changes code formatting to respect `black` coding style.
- Changes documentation to single-page layout.

## 0.6.1 (2020-05-25)

- Upgrades REANA-Commons package using latest Kubernetes Python client version.

## 0.6.0 (2019-12-20)

- Adds generic job manager class and provides example classes for CERN HTCondor
  and CERN Slurm clusters.
- Moves job controller to the same Kubernetes pod with the
  REANA-Workflow-Engine-\* (sidecar pattern).
- Adds sidecar container to the Kubernetes job pod if Kerberos authentication
  is required.
- Provides user secrets to the job container runtime tasks.
- Refactors job monitoring using singleton pattern.

## 0.5.1 (2019-04-23)

- Pins `urllib3` due to a conflict while installing `Kubernetes` Python
  library.
- Fixes documenation build badge.

## 0.5.0 (2019-04-23)

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

## 0.4.0 (2018-11-06)

- Improves REST API documentation rendering.
- Changes license to MIT.

## 0.3.2 (2018-09-26)

- Adapts Kubernetes API adaptor to mount shared volumes on jobs as CEPH
  `persistentVolumeClaim`'s (managed by `reana-cluster`) instead of plain
  CEPH volumes.

## 0.3.1 (2018-09-07)

- Pins REANA-Commons and REANA-DB dependencies.

## 0.3.0 (2018-08-10)

- Adds uwsgi for production deployments.
- Switches from pykube to official Kubernetes python client.
- Adds compatibility with latest Kubernetes.

## 0.2.0 (2018-04-19)

- Adds dockerignore file to ease developments.

## 0.1.0 (2018-01-30)

- Initial public release.
