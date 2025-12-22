FROM redhat/ubi9:latest
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ENV ATOAAS_ALLOW_NO_DB=1
ENV FLASK_SECRET_KEY="9J5zf4JKTQVc_LerK4Er593ydpsw4cDF-RpLjPqKVTj2j5ftzs3M0XsB36szQ1k0IkNIEwai2U7Lu-kC7HAHlQ=="
ENV JWT_SECRET_KEY="BUxpnRveoTG5A1ZVaRGPQYpwleNpwW8fdL6sceTeGrGbDWrCZgxu03Y18rCezPQjIBop8hPwsAfZ4BWsmcWusg=="

# System deps (libicu needed by PowerShell)
RUN dnf -y --allowerasing update && \
    dnf -y --allowerasing install \
      python3 python3-pip \
      curl unzip less \
      ca-certificates libicu && \
    update-ca-trust extract && \
    dnf clean all

# Python deps (cache-friendly)
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && rm -f /tmp/requirements.txt

# App code
COPY . /app



EXPOSE 5000

#set gunicorn to debug log level for testing/dev
# set gunicorn to debug log level for testing/dev
CMD ["gunicorn", "--capture-output", "--enable-stdio-inheritance", "--log-level", "debug", "-b", "0.0.0.0:5000", "flaskapp:app", "--workers", "1", "--threads", "8", "--timeout", "600"]


