FROM python:3.6-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update
RUN apt-get install -y vim-tiny krb5-user krb5-config libkrb5-dev \
                       libauthen-krb5-perl --no-install-recommends;
