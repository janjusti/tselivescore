FROM python:3.12-slim

WORKDIR /app

ENV TZ=America/Sao_Paulo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY src/reqs/requirements-base.txt .
RUN pip install --no-cache-dir -r requirements-base.txt

COPY src/ src/

ENTRYPOINT ["python", "src/tselivescore.py"]
