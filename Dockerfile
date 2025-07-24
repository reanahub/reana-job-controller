# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

# Use Ubuntu LTS base image
FROM docker.io/library/ubuntu:24.04

# Recognise target architecture
ARG TARGETARCH

# Use default answers in installation commands
ENV DEBIAN_FRONTEND=noninteractive

# Allow pip to install packages in the system site-packages dir
ENV PIP_BREAK_SYSTEM_PACKAGES=true

# Prepare list of Python dependencies
COPY requirements.txt /code/

# Install all system and Python dependencies in one go
# hadolint ignore=DL3008,DL3013
RUN apt-get update -y && \
    apt-get install --no-install-recommends -y \
      git \
      gcc \
      krb5-config \
      krb5-user \
      libauthen-krb5-simple-perl \
      libkrb5-dev \
      openssh-client \
      # matches version in setup.py/requirements.in
      python3-gssapi=1.8.2-1ubuntu1 \
      python3-pip \
      python3.12 \
      python3.12-dev \
      vim-tiny && \
    pip install --no-cache-dir --upgrade setuptools && \
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
      apt-get install --no-install-recommends -y wget alien gnupg2 condor; \
      wget -q -O ngbauth-submit.rpm https://linuxsoft.cern.ch/internal/repos/batch9al-stable/x86_64/os/Packages/n/ngbauth-submit-0.31-1.al9.cern.noarch.rpm; \
      wget -q -O myschedd.rpm https://linuxsoft.cern.ch/internal/repos/batch9al-stable/x86_64/os/Packages/m/myschedd-1.9-2.al9.cern.x86_64.rpm; \
      yes | alien -i myschedd.rpm; \
      yes | alien -i ngbauth-submit.rpm; \
      rm -rf myschedd.rpm ngbauth-submit.rpm; \
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
      elif echo "$COMPUTE_BACKENDS" | grep -q "compute4punch"; then \
        pip install --no-cache-dir ".[debug,mytoken,ssh]"; \
      else \
        pip install --no-cache-dir -e ".[debug]"; \
      fi \
    else \
      if echo "$COMPUTE_BACKENDS" | grep -q "htcondorcern"; then \
        pip install --no-cache-dir ".[htcondor]"; \
      elif echo "$COMPUTE_BACKENDS" | grep -q "compute4punch"; then \
        pip install --no-cache-dir ".[mytoken,ssh]"; \
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

# Delete default `ubuntu` user, as its UID (1000) clashes with REANA's default one
# See https://bugs.launchpad.net/cloud-images/+bug/2005129
RUN userdel -r ubuntu

# Expose ports to clients
EXPOSE 5000

# Run server
CMD ["flask", "run", "-h", "0.0.0.0"]

# Set image labels
LABEL org.opencontainers.image.authors="team@reanahub.io"
LABEL org.opencontainers.image.created="2024-11-29"
LABEL org.opencontainers.image.description="REANA reproducible analysis platform - job controller component"
LABEL org.opencontainers.image.documentation="https://reana-job-controller.readthedocs.io/"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/reanahub/reana-job-controller"
LABEL org.opencontainers.image.title="reana-job-controller"
LABEL org.opencontainers.image.url="https://github.com/reanahub/reana-job-controller"
LABEL org.opencontainers.image.vendor="reanahub"
# x-release-please-start-version
LABEL org.opencontainers.image.version="0.9.5"
# x-release-please-end
