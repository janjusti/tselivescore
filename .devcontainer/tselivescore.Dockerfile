FROM python:3.9.14-alpine3.16 as base
RUN apk update
# requirements
RUN mkdir /temp
COPY src /temp/src
RUN pip install --upgrade pip
RUN pip install -r /temp/src/reqs/requirements-base.txt

### dsv
FROM base as dsv
RUN pip install -r /temp/src/reqs/requirements-dsv.txt
RUN mkdir /workspace
# packages
RUN apk add git
# terminal
RUN apk add --no-cache bash starship
COPY .devcontainer/configs /root