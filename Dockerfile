FROM python:2.7.12

# Set Python-related environment variables to reduce annoying-ness
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1
ENV PIP_DISABLE_PIP_VERSION_CHECK 1
ENV LANG C.UTF-8

# Setup environment/dependencies
RUN update-alternatives --install /bin/sh sh /bin/bash 10
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
                    build-essential \
                    memcached && \
    rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1001 app && useradd -g app --uid 1001 --shell /usr/sbin/nologin app
COPY . /app
RUN pip install -U 'pip>=8' && \
    pip install -r /app/requirements.txt
RUN chown -R app:app /app
WORKDIR /app
USER app

ENTRYPOINT ["python", "/app/quickstart.py"]
