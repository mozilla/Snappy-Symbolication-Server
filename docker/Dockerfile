FROM python:2.7.12

RUN groupadd --gid 1001 app && useradd -g app --uid 1001 --shell /usr/sbin/nologin app

# Set Python-related environment variables to reduce annoying-ness
ENV PYTHONUNBUFFERED 1
ENV PYTHONDONTWRITEBYTECODE 1
ENV PIP_DISABLE_PIP_VERSION_CHECK 1
ENV LANG C.UTF-8

EXPOSE 8080
CMD ["/app/docker/start_services.sh"]
WORKDIR /app
RUN update-alternatives --install /bin/sh sh /bin/bash 10

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
                    build-essential \
                    memcached && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt && \
    pip install flake8

USER app

COPY . /app
