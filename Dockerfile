# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

# Install base image and its dependencies
FROM python:3.8-slim-buster
# hadolint ignore=DL3008,DL3009,DL3013
RUN apt-get update && \
    apt-get install -y --no-install-recommends vim-tiny && \
    pip install --upgrade pip

# Install Kerberos dependencies
# hadolint ignore=DL3008
RUN export DEBIAN_FRONTEND=noninteractive ;\
    apt-get -yq install --no-install-recommends \
                        krb5-user \
                        krb5-config \
                        libkrb5-dev \
                        libauthen-krb5-perl \
                        gcc;
COPY etc/krb5.conf /etc/krb5.conf

# Default compute backend is Kubernetes
ARG COMPUTE_BACKENDS=kubernetes

# CERN HTCondor part taken from https://gitlab.cern.ch/batch-team/condorsubmit
# hadolint ignore=DL3008,DL3009,DL4006
RUN if echo "$COMPUTE_BACKENDS" | grep -q "htcondorcern"; then \
      set -e;\
      export DEBIAN_FRONTEND=noninteractive ;\
      apt-get -yq install --no-install-recommends wget alien gnupg2 ;\
      wget -O ngbauth-submit.rpm http://linuxsoft.cern.ch/internal/repos/batch7-stable/x86_64/os/Packages/ngbauth-submit-0.24-3.el7.noarch.rpm; \
      wget -O myschedd.rpm http://linuxsoft.cern.ch/internal/repos/batch7-stable/x86_64/os/Packages/myschedd-1.7-2.el7.x86_64.rpm; \
      yes | alien -i myschedd.rpm; \
      yes | alien -i ngbauth-submit.rpm; \
      wget -qO - http://research.cs.wisc.edu/htcondor/debian/HTCondor-Release.gpg.key | apt-key add -; \
      echo "deb https://research.cs.wisc.edu/htcondor/debian/8.9/buster buster contrib" >>/etc/apt/sources.list; \
      apt-get update; \
      apt-get install -y --no-install-recommends condor; \
      apt-get -y remove gnupg2 wget alien; \
      apt-get clean; \
    fi

# CERN Slurm backend requires SSH to headnode
# hadolint ignore=DL3008,DL4006
RUN if echo "$COMPUTE_BACKENDS" | grep -q "slurmcern"; then \
      export DEBIAN_FRONTEND=noninteractive ;\
      apt-get -yq install openssh-client \
                          --no-install-recommends; \
    fi

# Add HTCondor related files
RUN mkdir -p /etc/myschedd
COPY etc/myschedd.yaml /etc/myschedd/
COPY etc/10_cernsubmit.config /etc/condor/config.d/
COPY etc/ngbauth-submit /etc/sysconfig/
COPY etc/ngauth_batch_crypt_pub.pem /etc/
COPY etc/cerngridca.crt /usr/local/share/ca-certificates/cerngridca.crt
COPY etc/cernroot.crt /usr/local/share/ca-certificates/cernroot.crt
COPY etc/job_wrapper.sh etc/job_wrapper.sh
RUN chmod +x /etc/job_wrapper.sh
RUN update-ca-certificates

# Install dependencies
COPY requirements.txt /code/
RUN pip install --no-cache-dir -r /code/requirements.txt

# Copy cluster component source code
WORKDIR /code
COPY . /code

# Are we debugging?
ARG DEBUG=0
RUN if [ "${DEBUG}" -gt 0 ]; then pip install -e ".[debug]"; else pip install .; fi;

# Are we building with locally-checked-out shared modules?
# hadolint ignore=SC2102
RUN if test -e modules/reana-commons; then pip install -e modules/reana-commons[kubernetes] --upgrade; fi
RUN if test -e modules/reana-db; then pip install -e modules/reana-db --upgrade; fi

# Check if there are broken requirements
RUN pip check

# Set useful environment variables
ENV COMPUTE_BACKENDS=$COMPUTE_BACKENDS \
    FLASK_APP=reana_job_controller/app.py \
    TERM=xterm

# Expose ports to clients
EXPOSE 5000

# Run server
CMD ["flask", "run", "-h", "0.0.0.0"]
