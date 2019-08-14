FROM python:3.6-slim

RUN apt-get update && \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get install -y vim-tiny krb5-user krb5-config libkrb5-dev \
                       libauthen-krb5-perl --no-install-recommends;
