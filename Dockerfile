# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

# Install base image and its dependencies
FROM python:3.6-slim
RUN apt-get update && \
    apt-get install -y vim-tiny && \
    pip install --upgrade pip

# Install Kerberos dependencies
RUN export DEBIAN_FRONTEND=noninteractive ;\
    apt-get -yq install krb5-user \
                        krb5-config \
                        libkrb5-dev \
                        libauthen-krb5-perl \
                        gcc;
ADD etc/krb5.conf /etc/krb5.conf

# Default compute backend is Kubernetes
ARG COMPUTE_BACKENDS=kubernetes

# CERN HTCondor part taken from https://gitlab.cern.ch/batch-team/condorsubmit
RUN if echo "$COMPUTE_BACKENDS" | grep -q "htcondorcern"; then \
      export DEBIAN_FRONTEND=noninteractive ;\
      apt-get -yq install wget alien gnupg2 ;\
      wget -O ngbauth-submit.rpm http://linuxsoft.cern.ch/internal/repos/batch7-stable/x86_64/os/Packages/ngbauth-submit-0.23-1.el7.noarch.rpm; \
      wget -O myschedd.rpm http://linuxsoft.cern.ch/internal/repos/batch7-stable/x86_64/os/Packages/myschedd-1.5-1.el7.x86_64.rpm; \
      yes | alien -i myschedd.rpm; \
      yes | alien -i ngbauth-submit.rpm; \
      wget -qO - http://research.cs.wisc.edu/htcondor/debian/HTCondor-Release.gpg.key | apt-key add -; \
      echo "deb https://research.cs.wisc.edu/htcondor/debian/8.9/buster buster contrib" >>/etc/apt/sources.list; \
      apt-get update; \
      apt-get install -y condor --no-install-recommends; \
      apt-get -y remove gnupg2 wget alien; \
    fi

# CERN Slurm backend requires SSH to headnode
RUN if echo "$COMPUTE_BACKENDS" | grep -q "slurmcern"; then \
      export DEBIAN_FRONTEND=noninteractive ;\
      apt-get -yq install openssh-client \
                          --no-install-recommends; \
    fi

# Add HTCondor related files
RUN mkdir -p /etc/myschedd
ADD etc/myschedd.yaml /etc/myschedd/
ADD etc/10_cernsubmit.config /etc/condor/config.d/
ADD etc/ngbauth-submit /etc/sysconfig/
ADD etc/ngauth_batch_crypt_pub.pem /etc/
ADD etc/cerngridca.crt /usr/local/share/ca-certificates/cerngridca.crt
ADD etc/cernroot.crt /usr/local/share/ca-certificates/cernroot.crt
ADD etc/job_wrapper.sh etc/job_wrapper.sh
RUN chmod +x /etc/job_wrapper.sh
RUN update-ca-certificates

# Install dependencies
COPY requirements.txt /code/
RUN pip install -r /code/requirements.txt

# Copy cluster component source code
WORKDIR /code
COPY . /code

# Are we debugging?
ARG DEBUG=0
RUN if [ "${DEBUG}" -gt 0 ]; then pip install pip install -e ".[debug]"; else pip install .; fi;

# Are we building with locally-checked-out shared modules?
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
