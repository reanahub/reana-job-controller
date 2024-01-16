# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

# Use Ubuntu LTS base image
FROM docker.io/library/ubuntu:20.04

# Recognise target architecture
ARG TARGETARCH

# Use default answers in installation commands
ENV DEBIAN_FRONTEND=noninteractive

# Use distutils provided by the standard Python library instead of the vendored one in
# setuptools, so that editable installations are stored in the right directory.
# See https://github.com/pypa/setuptools/issues/3301
ENV SETUPTOOLS_USE_DISTUTILS=stdlib

# Prepare list of Python dependencies
COPY requirements.txt /code/

# Install all system and Python dependencies in one go
# hadolint ignore=DL3008,DL3013
RUN apt-get update -y && \
    apt-get install --no-install-recommends -y \
      gcc \
      krb5-config \
      krb5-user \
      libauthen-krb5-perl \
      libkrb5-dev \
      openssh-client \
      python3-gssapi \
      python3-pip \
      python3.8 \
      python3.8-dev \
      vim-tiny && \
    pip install --no-cache-dir --upgrade pip setuptools && \
    pip install --no-cache-dir -r /code/requirements.txt && \
    apt-get remove -y \
      gcc && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Default compute backend is Kubernetes
ARG COMPUTE_BACKENDS=kubernetes

# Install CERN HTCondor compute backend dependencies (if necessary)
# hadolint ignore=DL3008,DL4006
RUN if echo "$COMPUTE_BACKENDS" | grep -q "htcondorcern"; then \
      set -e; \
      apt-get update -y; \
      apt-get install --no-install-recommends -y wget alien gnupg2 rand; \
      wget -q -O ngbauth-submit.rpm https://linuxsoft.cern.ch/internal/repos/batch8s-stable/x86_64/os/Packages/n/ngbauth-submit-0.26-2.el8s.noarch.rpm; \
      wget -q -O myschedd.rpm https://linuxsoft.cern.ch/internal/repos/batch8s-stable/x86_64/os/Packages/m/myschedd-1.9-2.el8s.x86_64.rpm; \
      yes | alien -i myschedd.rpm; \
      yes | alien -i ngbauth-submit.rpm; \
      rm -rf myschedd.rpm ngbauth-submit.rpm; \
      wget -qO - https://research.cs.wisc.edu/htcondor/repo/keys/HTCondor-9.0-Key | apt-key add -; \
      echo "deb https://research.cs.wisc.edu/htcondor/repo/ubuntu/9.0 focal main" >> /etc/apt/sources.list; \
      echo "deb-src https://research.cs.wisc.edu/htcondor/repo/ubuntu/9.0 focal main" >> /etc/apt/sources.list; \
      apt-get update -y; \
      apt-get install --no-install-recommends -y condor; \
      apt-get remove -y gnupg2 wget alien; \
      apt-get autoremove -y; \
      apt-get clean; \
      rm -rf /var/lib/apt/lists/*; \
    fi

# Copy Kerberos related configuration files
COPY etc/krb5.conf /etc/krb5.conf

# Copy CERN HTCondor compute backend related configuration files
RUN mkdir -p /etc/myschedd
COPY etc/myschedd.yaml /etc/myschedd/
COPY etc/10_cernsubmit.config /etc/condor/config.d/
COPY etc/10_cernsubmit.erb /etc/condor/config.d/
COPY etc/ngbauth-submit /etc/sysconfig/
COPY etc/ngauth_batch_crypt_pub.pem /etc/
COPY etc/cerngridca.crt /usr/local/share/ca-certificates/cerngridca.crt
COPY etc/cernroot.crt /usr/local/share/ca-certificates/cernroot.crt
COPY etc/job_wrapper.sh /etc/job_wrapper.sh
RUN chmod +x /etc/job_wrapper.sh && \
    update-ca-certificates

# Copy cluster component source code
WORKDIR /code
COPY . /code

# Are we debugging?
ARG DEBUG=0
# hadolint ignore=DL3013,DL4006,SC1075
RUN if [ "${DEBUG}" -gt 0 ]; then \
      if echo "$COMPUTE_BACKENDS" | grep -q "htcondorcern"; then \
        pip install --no-cache-dir -e ".[debug,htcondor]"; \
      else \
        pip install --no-cache-dir -e ".[debug]"; \
      fi \
    else \
      if echo "$COMPUTE_BACKENDS" | grep -q "htcondorcern"; then \
        pip install --no-cache-dir ".[htcondor]"; \
      else \
        pip install --no-cache-dir .; \
      fi \
    fi

# Are we building with locally-checked-out shared modules?
# hadolint ignore=DL3013
RUN if test -e modules/reana-commons; then \
      if [ "${DEBUG}" -gt 0 ]; then \
        pip install --no-cache-dir -e "modules/reana-commons[kubernetes]" --upgrade; \
      else \
        pip install --no-cache-dir "modules/reana-commons[kubernetes]" --upgrade; \
      fi \
    fi; \
    if test -e modules/reana-db; then \
      if [ "${DEBUG}" -gt 0 ]; then \
        pip install --no-cache-dir -e "modules/reana-db" --upgrade; \
      else \
        pip install --no-cache-dir "modules/reana-db" --upgrade; \
      fi \
    fi

# Check for any broken Python dependencies
RUN pip check

# Set useful environment variables
ENV COMPUTE_BACKENDS=$COMPUTE_BACKENDS \
    FLASK_APP=reana_job_controller/app.py \
    TERM=xterm

# Expose ports to clients
EXPOSE 5000

# Run server
CMD ["flask", "run", "-h", "0.0.0.0"]

# Set image labels
LABEL org.opencontainers.image.authors="team@reanahub.io"
LABEL org.opencontainers.image.created="2023-12-12"
LABEL org.opencontainers.image.description="REANA reproducible analysis platform - job controller component"
LABEL org.opencontainers.image.documentation="https://reana-job-controller.readthedocs.io/"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/reanahub/reana-job-controller"
LABEL org.opencontainers.image.title="reana-job-controller"
LABEL org.opencontainers.image.url="https://github.com/reanahub/reana-job-controller"
LABEL org.opencontainers.image.vendor="reanahub"
# x-release-please-start-version
LABEL org.opencontainers.image.version="0.9.2"
# x-release-please-end
