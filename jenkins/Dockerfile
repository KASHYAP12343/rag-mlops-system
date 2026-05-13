FROM jenkins/jenkins:lts

USER root

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    ca-certificates \
    gnupg \
    lsb-release \
    apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# ── Docker CLI (to build/push images from inside Jenkins) ───────────────────
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
       | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo \
       "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
       https://download.docker.com/linux/debian \
       $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
       | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# ── Trivy (container image vulnerability scanner) ───────────────────────────
RUN curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh \
    | sh -s -- -b /usr/local/bin

# ── Add jenkins user to docker group (allows socket access) ─────────────────
RUN groupadd -f docker && usermod -aG docker jenkins

USER jenkins

# Jenkins can now:
#   ✅ create Python venvs and run pytest
#   ✅ run docker build / docker push via mounted socket
#   ✅ run trivy scan on built images
#   ✅ run curl health checks