FROM python:3.9.14-alpine3.16 as base
RUN apk update
# requirements
RUN mkdir /temp
COPY src /temp/src
RUN pip install --upgrade pip
RUN pip install -r /temp/src/reqs/requirements-base.txt
# terminal
RUN apk add --no-cache bash starship
COPY .devcontainer/configs /root
# timezone
RUN apk add --no-cache tzdata
ENV TZ=America/Sao_Paulo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

### live
FROM base as live
RUN echo ":D"

### dsv
FROM base as dsv
RUN pip install -r /temp/src/reqs/requirements-dsv.txt
RUN mkdir /workspace
# packages
RUN apk add git