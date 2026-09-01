# check=skip=SecretsUsedInArgOrEnv
# The skip above concerns NSS_WRAPPER_PASSWD, which holds a file path
# for nss_wrapper, not a secret. The check cannot be skipped per line.

# This file is part of REANA.
# Copyright (C) 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 CERN.
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
      libnss-wrapper \
      krb5-config \
      krb5-user \
      libauthen-krb5-simple-perl \
      libkrb5-dev \
      libpcre3 \
      libpcre3-dev \
      libpython3.12 \
      openssh-client \
      # matches version in setup.py/requirements.in
      python3-gssapi=1.8.2-1ubuntu1 \
      python3-pip \
      python3.12 \
      python3.12-dev \
      vim-tiny && \
    pip install --no-cache-dir --upgrade 'setuptools<81' && \
    pip install --no-cache-dir -r /code/requirements.txt && \
    apt-get remove -y \
      gcc \
      libpcre3-dev && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Default compute backend is Kubernetes
ARG COMPUTE_BACKENDS=kubernetes
ARG AUTHEN_KRB5_VERSION=1.906
ARG AUTHEN_KRB5_SHA256=2dc0928efb13b5f305df3452088e63f92b67acea87fbd470308f460f79126e84
ARG CERN_CA_CERTS_VERSION=20260729-1
ARG CERN_CA_CERTS_SHA256=5a9f20acf950132ed150291a7250a21ac2b77fcb54f2bf4ec7ad4c36c7aea990
ARG CERN_KRB5_CONF_VERSION=1.3-8
ARG CERN_KRB5_CONF_DEFAULTS_SHA256=bc02a137b5be334d02d92e6743b82662c8fe6e6676f16f5793901042dd6b111f
ARG CERN_KRB5_CONF_REALM_SHA256=f50f12f4eb0abd2762fa5b030006e9a5515ed467e02cb03ddf658bc83c56837b
ARG NGBAUTH_SUBMIT_VERSION=1.1-1
ARG NGBAUTH_SUBMIT_SHA256=1c706ce55666cd1664f67e6a5fc304ed6326d30b4861e8c5f6c7a6d9d65413fb
ARG MYSCHEDD_VERSION=1.9-3
ARG MYSCHEDD_AMD64_SHA256=21e9965b7b5f98fea26cb845f5f65df37e89dfc276d8ddca8195832fa3bc213f
ARG MYSCHEDD_ARM64_SHA256=84638f08539f041c95a22bbe81d6fb415ec9b257b3806feacb331673d1ef388c

# Refresh CERN package versions and SHA-256 pins together. Exact package URLs
# may disappear when CERN prunes superseded versions from the repository.
# Install the CERN-managed Kerberos configuration for CERN compute backends.
# hadolint ignore=DL3008,DL4006
RUN set -e; \
    if echo "$COMPUTE_BACKENDS" | grep -Eq "htcondorcern|slurmcern"; then \
      CERN_CONFIG_REPOSITORY="https://linuxsoft.cern.ch/cern/rhel/9/CERN/x86_64/Packages"; \
      apt-get update -y; \
      apt-get install --no-install-recommends -y wget rpm2cpio cpio; \
      wget -q -O /cern-ca-certs.rpm \
        "$CERN_CONFIG_REPOSITORY/c/CERN-CA-certs-$CERN_CA_CERTS_VERSION.rh9.cern.noarch.rpm"; \
      echo "$CERN_CA_CERTS_SHA256  /cern-ca-certs.rpm" | sha256sum -c -; \
      rpm2cpio /cern-ca-certs.rpm > /cern-ca-certs.cpio; \
      wget -q -O /cern-krb5-defaults.rpm \
        "$CERN_CONFIG_REPOSITORY/c/cern-krb5-conf-defaults-cernch-$CERN_KRB5_CONF_VERSION.rh9.cern.noarch.rpm"; \
      echo "$CERN_KRB5_CONF_DEFAULTS_SHA256  /cern-krb5-defaults.rpm" | sha256sum -c -; \
      rpm2cpio /cern-krb5-defaults.rpm > /cern-krb5-defaults.cpio; \
      wget -q -O /cern-krb5-realm.rpm \
        "$CERN_CONFIG_REPOSITORY/c/cern-krb5-conf-realm-cernch-$CERN_KRB5_CONF_VERSION.rh9.cern.noarch.rpm"; \
      echo "$CERN_KRB5_CONF_REALM_SHA256  /cern-krb5-realm.rpm" | sha256sum -c -; \
      rpm2cpio /cern-krb5-realm.rpm > /cern-krb5-realm.cpio; \
      cpio -idmv -D / < /cern-krb5-defaults.cpio; \
      cpio -idmv -D / < /cern-krb5-realm.cpio; \
      mkdir -p /tmp/cern-ca-certs; \
      cpio -idmv -D /tmp/cern-ca-certs < /cern-ca-certs.cpio; \
      certificate_count=0; \
      for certificate in /tmp/cern-ca-certs/etc/pki/tls/certs/*.pem; do \
        if [ "$(tr -d '\r' < "$certificate" | grep -c '^-----BEGIN CERTIFICATE-----$')" -ne 1 ]; then \
          continue; \
        fi; \
        certificate_name=$(basename "$certificate" .pem | \
          sed -E 's/[^[:alnum:]_-]+/-/g; s/^-+//; s/-+$//'); \
        test -n "$certificate_name"; \
        certificate_path="/usr/local/share/ca-certificates/cern-${certificate_name}.crt"; \
        test ! -e "$certificate_path"; \
        install -m 0644 "$certificate" "$certificate_path"; \
        certificate_count=$((certificate_count + 1)); \
      done; \
      test "$certificate_count" -ge 3; \
      rm -f \
        /cern-ca-certs.rpm \
        /cern-ca-certs.cpio \
        /cern-krb5-defaults.rpm \
        /cern-krb5-defaults.cpio \
        /cern-krb5-realm.rpm \
        /cern-krb5-realm.cpio; \
      rm -rf /tmp/cern-ca-certs; \
      apt-get remove -y wget rpm2cpio cpio; \
      apt-get autoremove -y; \
      apt-get clean; \
      rm -rf /var/lib/apt/lists/*; \
      grep -q "dns_canonicalize_hostname = fallback" \
        /etc/krb5.conf.d/cern-defaults-dns_canon_host_fallback.conf; \
    fi

COPY patches/Authen-Krb5-cc_copy_creds.patch /tmp/

# Install CERN HTCondor compute backend dependencies (if necessary)
# Prefer exact packages from stable after promotion. Keep QA as a temporary
# fallback because the aarch64 packages are not available from stable yet.
# One digest identifies the expected artefact in either repository. Fall back
# only when stable is unavailable; a checksum mismatch must fail the build.
# Kubernetes DNS keeps ngass.cern.ch as the forward canonical name. CERN's
# Kerberos policy enables reverse DNS; align the producer's private profile so
# its fallback lookup can discover the load-balanced ngauth service principal.
# hadolint ignore=DL3008,DL4006
RUN set -e; \
    if echo "$COMPUTE_BACKENDS" | grep -q "htcondorcern"; then \
      set -e; \
      case "$TARGETARCH" in \
        amd64) RPM_ARCH=x86_64; MYSCHEDD_SHA256="$MYSCHEDD_AMD64_SHA256" ;; \
        arm64) RPM_ARCH=aarch64; MYSCHEDD_SHA256="$MYSCHEDD_ARM64_SHA256" ;; \
        *) echo "Unsupported HTCondor target architecture: $TARGETARCH" >&2; exit 1 ;; \
      esac; \
      CERN_BATCH_STABLE_REPOSITORY="https://linuxsoft.cern.ch/internal/repos/batch9el-stable/$RPM_ARCH/os/Packages"; \
      CERN_BATCH_QA_REPOSITORY="https://linuxsoft.cern.ch/internal/repos/batch9el-qa/$RPM_ARCH/os/Packages"; \
      apt-get update -y; \
      apt-get install --no-install-recommends -y wget rpm2cpio cpio gnupg2 condor cpanminus gcc make patch; \
      wget -q -O /tmp/Authen-Krb5.tar.gz "https://cpan.metacpan.org/authors/id/O/OD/ODENBACH/Authen-Krb5-$AUTHEN_KRB5_VERSION.tar.gz"; \
      echo "$AUTHEN_KRB5_SHA256  /tmp/Authen-Krb5.tar.gz" | sha256sum -c -; \
      tar -xzf /tmp/Authen-Krb5.tar.gz -C /tmp; \
      patch -d "/tmp/Authen-Krb5-$AUTHEN_KRB5_VERSION" -p1 < /tmp/Authen-Krb5-cc_copy_creds.patch; \
      cpanm --notest --mirror https://cpan.metacpan.org --mirror-only "/tmp/Authen-Krb5-$AUTHEN_KRB5_VERSION"; \
      perl -MAuthen::Krb5 -e 'die "cc_copy_creds is unavailable\n" unless Authen::Krb5->can("cc_copy_creds")'; \
      if wget -q -O /ngbauth-submit.rpm \
          "$CERN_BATCH_STABLE_REPOSITORY/n/ngbauth-submit-$NGBAUTH_SUBMIT_VERSION.rh9.cern.noarch.rpm"; then \
        echo "$NGBAUTH_SUBMIT_SHA256  /ngbauth-submit.rpm" | sha256sum -c -; \
        rpm2cpio /ngbauth-submit.rpm > /ngbauth-submit.cpio; \
        echo "Using ngbauth-submit from the stable repository."; \
      else \
        echo "Stable ngbauth-submit is unavailable; using QA."; \
        rm -f /ngbauth-submit.rpm /ngbauth-submit.cpio; \
        wget -q -O /ngbauth-submit.rpm \
          "$CERN_BATCH_QA_REPOSITORY/n/ngbauth-submit-$NGBAUTH_SUBMIT_VERSION.rh9.cern.noarch.rpm"; \
        echo "$NGBAUTH_SUBMIT_SHA256  /ngbauth-submit.rpm" | sha256sum -c -; \
        rpm2cpio /ngbauth-submit.rpm > /ngbauth-submit.cpio; \
      fi; \
      if wget -q -O /myschedd.rpm \
          "$CERN_BATCH_STABLE_REPOSITORY/m/myschedd-$MYSCHEDD_VERSION.rh9.cern.$RPM_ARCH.rpm"; then \
        echo "$MYSCHEDD_SHA256  /myschedd.rpm" | sha256sum -c -; \
        rpm2cpio /myschedd.rpm > /myschedd.cpio; \
        echo "Using myschedd from the stable repository."; \
      else \
        echo "Stable myschedd is unavailable; using QA."; \
        rm -f /myschedd.rpm /myschedd.cpio; \
        wget -q -O /myschedd.rpm \
          "$CERN_BATCH_QA_REPOSITORY/m/myschedd-$MYSCHEDD_VERSION.rh9.cern.$RPM_ARCH.rpm"; \
        echo "$MYSCHEDD_SHA256  /myschedd.rpm" | sha256sum -c -; \
        rpm2cpio /myschedd.rpm > /myschedd.cpio; \
      fi; \
      cpio -idmv -D / < /myschedd.cpio; \
      cpio -idmv -D / < /ngbauth-submit.cpio; \
      sed -i -E \
        's/^[[:space:]]*rdns[[:space:]]*=[[:space:]]*false[[:space:]]*$/ rdns = true/' \
        /usr/share/ngbauth-submit/krb5.conf.no_rdns; \
      grep -Eq '^[[:space:]]*rdns[[:space:]]*=[[:space:]]*true[[:space:]]*$' \
        /usr/share/ngbauth-submit/krb5.conf.no_rdns; \
      rm -rf "/tmp/Authen-Krb5-$AUTHEN_KRB5_VERSION"; \
      rm -f /tmp/Authen-Krb5.tar.gz /myschedd.rpm /myschedd.cpio /ngbauth-submit.rpm /ngbauth-submit.cpio; \
      apt-get remove -y gnupg2 wget rpm2cpio cpio cpanminus gcc make patch; \
      apt-get autoremove -y; \
      apt-get clean; \
      rm -rf /var/lib/apt/lists/*; \
      test -x /usr/bin/myschedd; \
      test -x /usr/bin/myschedd.sh; \
      perl -T -c /usr/bin/batch_krb5_credential; \
    fi; \
    rm -f /tmp/Authen-Krb5-cc_copy_creds.patch

# Load REANA Kerberos defaults and any CERN-managed snippets installed above.
COPY etc/krb5.conf /etc/krb5.conf
COPY etc/krb5.conf.d/ /etc/krb5.conf.d/

# Copy CERN HTCondor compute backend related configuration files
RUN mkdir -p /etc/myschedd
COPY etc/myschedd.yaml /etc/myschedd/
COPY etc/10_cernsubmit.config /etc/condor/config.d/
COPY etc/10_cernsubmit.erb /etc/condor/config.d/
COPY etc/ngbauth-submit /etc/sysconfig/
COPY etc/ngauth_batch_crypt_pub.pem /etc/
COPY etc/job_wrapper.sh /etc/job_wrapper.sh
RUN chmod +x /etc/job_wrapper.sh && \
    update-ca-certificates

# Resolve libnss_wrapper at build time and prepare runtime directories
RUN LIBNSS_WRAPPER_PATH="" && \
    for candidate in $(dpkg -L libnss-wrapper); do \
      case "${candidate}" in \
        */libnss_wrapper.so) \
          LIBNSS_WRAPPER_PATH="${candidate}"; \
          break; \
          ;; \
      esac; \
    done && \
    test -n "${LIBNSS_WRAPPER_PATH}" && \
    mkdir -p /usr/local/lib /var/run/nss_wrapper && \
    ln -sf "${LIBNSS_WRAPPER_PATH}" /usr/local/lib/libnss_wrapper.so && \
    chown -R 1000:0 /var/run/nss_wrapper && \
    chmod -R g+rwx /var/run/nss_wrapper

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
    K8S_USE_SECURITY_CONTEXT=True \
    LIBNSS_WRAPPER_PATH=/usr/local/lib/libnss_wrapper.so \
    NSS_WRAPPER_GROUP=/var/run/nss_wrapper/group \
    NSS_WRAPPER_PASSWD=/var/run/nss_wrapper/passwd \
    TERM=xterm

# Default caches and HTCondor runtime files live under /tmp so the
# OpenShift-style arbitrary UID/GID path remains writable too.
ENV HOME=/tmp/reana-job-controller \
    TMPDIR=/tmp \
    WORKFLOW_RUNTIME_GROUP_NAME=root \
    WORKFLOW_RUNTIME_USER_GID=0 \
    WORKFLOW_RUNTIME_USER_NAME=reana \
    WORKFLOW_RUNTIME_USER_UID=1000 \
    XDG_CACHE_HOME=/tmp/reana-job-controller/.cache

# Expose ports to clients
EXPOSE 5000

# Run server. In a full REANA deployment the wrapper is still invoked via
# reana-workflow-controller, but the wrapper itself decides between uwsgi and
# the Flask development server depending on runtime context.
USER 1000:0
CMD ["python3", "-m", "reana_job_controller.nss_wrapper"]

# Set image labels
LABEL org.opencontainers.image.authors="team@reanahub.io"
LABEL org.opencontainers.image.created="2026-06-07"
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
