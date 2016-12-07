FROM python:3.5
ADD requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt
COPY reana_job_controller /code
WORKDIR /code
RUN adduser --uid 1000 --disabled-password --gecos reanauser && \
    chown -R reanauser:reanauser /code
USER reanauser
EXPOSE 5000
CMD ["python", "app.py"]
