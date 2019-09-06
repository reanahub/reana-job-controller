# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

FROM python:3.6-slim

ENV TERM=xterm

# Hardcoded, this needs to be replaced
# by setting these attributes  
# in the kubernetes cluster configuration
ENV HTCONDOR_ADDR="<128.135.158.176:9618?addrs=128.135.158.176-9618+[--1]-9618&noUDP&sock=954400_984a_3>"

RUN apt-get update && \
    apt-get install -y vim-tiny && \
    pip install --upgrade pip && \
    pip install htcondor==8.9.1 retrying


ARG COMPUTE_BACKENDS=kubernetes
#CERN HTCondor part taken from https://gitlab.cern.ch/batch-team/condorsubmit
RUN case $COMPUTE_BACKENDS in \
    *"htcondorcern"*) \
      export DEBIAN_FRONTEND=noninteractive ;\
      apt-get -yq install wget alien gnupg2 \
                                     krb5-user \
                                     krb5-config \
                                     libkrb5-dev \
                                     libauthen-krb5-perl \
                                     --no-install-recommends; \
      wget -O ngbauth-submit.rpm http://linuxsoft.cern.ch/internal/repos/batch7-stable/x86_64/os/Packages/ngbauth-submit-0.23-1.el7.noarch.rpm; \
      wget -O cernbatchsubmit.rpm http://linuxsoft.cern.ch/internal/repos/batch7-stable/x86_64/os/Packages/cernbatchsubmit-0.1.0-1.el7.x86_64.rpm; \
      yes | alien -i cernbatchsubmit.rpm; \
      yes | alien -i ngbauth-submit.rpm; \
      wget -qO - http://research.cs.wisc.edu/htcondor/debian/HTCondor-Release.gpg.key | apt-key add -; \
      echo "deb https://research.cs.wisc.edu/htcondor/debian/8.8/buster buster contrib" >>/etc/apt/sources.list; \
      apt-get update; \
      apt-get install -y condor --no-install-recommends; \
      apt-get -y remove gnupg2 wget alien; \
      ;; \
    *) \
esac

ADD etc/cernsubmit.yaml /etc/condor/
ADD etc/10_cernsubmit.config /etc/condor/config.d/

ADD etc/krb5.conf /etc/krb5.conf
ADD etc/ngbauth-submit /etc/sysconfig/
ADD etc/ngauth_batch_crypt_pub.pem /etc/
ADD etc/cerngridca.crt /usr/local/share/ca-certificates/cerngridca.crt
ADD etc/cernroot.crt /usr/local/share/ca-certificates/cernroot.crt
ADD etc/job_wrapper.sh etc/job_wrapper.sh
RUN chmod +x /etc/job_wrapper.sh
RUN update-ca-certificates

COPY CHANGES.rst README.rst setup.py /code/
COPY reana_job_controller/version.py /code/reana_job_controller/
COPY reana_job_controller/htcondor_submit.py /code/htcondor_submit.py
WORKDIR /code
RUN pip install requirements-builder && \
    requirements-builder -l pypi setup.py | pip install -r /dev/stdin && \
    pip uninstall -y requirements-builder

COPY . /code

# Debug off by default
ARG DEBUG=0
RUN if [ "${DEBUG}" -gt 0 ]; then pip install -r requirements-dev.txt; pip install -e .; else pip install .; fi;

# Building with locally-checked-out shared modules?
RUN if test -e modules/reana-commons; then pip install modules/reana-commons --upgrade; fi
RUN if test -e modules/reana-db; then pip install modules/reana-db --upgrade; fi

# Check if there are broken requirements
RUN pip check

EXPOSE 5000

ENV COMPUTE_BACKENDS $COMPUTE_BACKENDS
ENV FLASK_APP reana_job_controller/app.py

CMD ["flask", "run", "-h", "0.0.0.0"]
