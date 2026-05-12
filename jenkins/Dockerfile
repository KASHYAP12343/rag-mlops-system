FROM jenkins/jenkins:lts

USER root

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git

USER jenkins

# Now Jenkins agent/container can:

# create venv
# install dependencies
# run pytest
# run docker commands later
# run curl health checks