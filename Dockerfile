# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

FROM python:3.6-slim

ENV TERM=xterm
RUN apt-get update && \
    apt-get install -y vim-tiny && \
    pip install --upgrade pip


#CERN HTCondor part https://gitlab.cern.ch/batch-team/condorsubmit
ARG HTCONDORCERN=0
RUN if [ "${HTCONDORCERN}" -eq 1 ]; then \
  DEBIAN_FRONTEND=noninteractive apt-get -yq install wget alien gnupg2 \
                                                                krb5-user \
                                                                krb5-config \
                                                                libkrb5-dev \
                                                                libauthen-krb5-perl \
                                                                --no-install-recommends; \
  wget -O ngbauth-submit.rpm http://linuxsoft.cern.ch/internal/repos/batch7-stable/x86_64/os/Packages/ngbauth-submit-0.23-1.el7.noarch.rpm; \
  wget -O cernbatchsubmit.rpm http://linuxsoft.cern.ch/internal/repos/batch7-stable/x86_64/os/Packages/cernbatchsubmit-0.1.0-1.el7.x86_64.rpm; \
  yes | alien -i cernbatchsubmit.rpm; \
  yes | alien -i ngbauth-submit.rpm; \
  wget -qO - https://research.cs.wisc.edu/htcondor/debian/HTCondor-Release.gpg.key | apt-key add -; \
  echo "deb http://research.cs.wisc.edu/htcondor/debian/8.8/stretch stretch contrib" >> /etc/apt/sources.list; \
  echo "deb-src http://research.cs.wisc.edu/htcondor/debian/8.8/stretch stretch contrib" >> /etc/apt/sources.list; \
  apt-get update; \
  apt-get install -y condor --no-install-recommends; \
  apt-get -y remove gnupg2 wget alien; \
fi;

ADD etc/cernsubmit.yaml /etc/condor/
ADD etc/10_cernsubmit.config /etc/condor/config.d/

ADD etc/krb5.conf /etc/krb5.conf
ADD etc/ngbauth-submit /etc/sysconfig/
ADD etc/ngauth_batch_crypt_pub.pem /etc/
ADD etc/cerngridca.crt /usr/local/share/ca-certificates/cerngridca.crt
ADD etc/cernroot.crt /usr/local/share/ca-certificates/cernroot.crt
RUN update-ca-certificates

COPY CHANGES.rst README.rst setup.py /code/
COPY reana_job_controller/version.py /code/reana_job_controller/
WORKDIR /code
RUN pip install requirements-builder && \
    requirements-builder -e all -l pypi setup.py | pip install -r /dev/stdin && \
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

ENV FLASK_APP reana_job_controller/app.py

CMD ["flask", "run", "-h", "0.0.0.0"]
