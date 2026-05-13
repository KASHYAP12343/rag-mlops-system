pipeline {

    agent any

    // ── Keep only last 5 builds & 10 days of history to prevent disk bloat ──
    options {
        buildDiscarder(logRotator(numToKeepStr: '5', daysToKeepStr: '10', artifactNumToKeepStr: '3'))
        timestamps()
    }

    environment {
        DOCKERHUB_REPO   = "mayank2101/rag-mlops"
        FRONTEND_REPO    = "mayank2101/rag-mlops-frontend"
        IMAGE_TAG        = "${env.BUILD_NUMBER}"
        GROQ_API_KEY     = "dummy-ci-key"
    }

    // Auto-trigger on every GitHub push via webhook
    triggers {
        githubPush()
    }

    stages {

        // ─────────────────────────────────────────────────────────────
        // Stage 1 — Install lightweight CI dependencies
        // ─────────────────────────────────────────────────────────────
        stage('Install Dependencies') {
            steps {
                sh '''
                python3 -m venv venv
                . venv/bin/activate
                pip install --upgrade pip
                pip install -r requirements-ci.txt
                # Install ansible + docker SDK into the venv for the Deploy stage
                pip install --quiet ansible docker requests
                
                # Download and install kubectl into venv/bin
                curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
                chmod +x kubectl
                mv kubectl venv/bin/
                '''
            }
        }

        // ─────────────────────────────────────────────────────────────
        // Stage 2 — Run automated tests
        // ─────────────────────────────────────────────────────────────
        stage('Run Tests') {
            steps {
                sh '''
                . venv/bin/activate
                pytest -v --tb=short
                '''
            }
            post {
                always {
                    // Publish JUnit XML results if present
                    junit allowEmptyResults: true, testResults: '**/test-results/*.xml'
                }
            }
        }

        // ─────────────────────────────────────────────────────────────
        // Stage 3 — Build Docker image
        // DOCKER_BUILDKIT=1 enables advanced caching — model layer
        // is cached separately from pip install layer
        // ─────────────────────────────────────────────────────────────
        stage('Build Docker Image') {
            steps {
                sh '''
                DOCKER_BUILDKIT=0 docker build \
                    --build-arg BUILD_NUMBER=${BUILD_NUMBER} \
                    -t ${DOCKERHUB_REPO}:${IMAGE_TAG} \
                    -t ${DOCKERHUB_REPO}:latest \
                    .
                '''
            }
        }

        // ─────────────────────────────────────────────────────────────
        // Stage 4 — Build Frontend Docker image
        // Multi-stage build: Node 20 compiles Vite/React → nginx serves
        // ─────────────────────────────────────────────────────────────
        stage('Build Frontend Image') {
            steps {
                sh '''
                DOCKER_BUILDKIT=0 docker build \
                    -t ${FRONTEND_REPO}:${IMAGE_TAG} \
                    -t ${FRONTEND_REPO}:latest \
                    ./frontend
                '''
            }
        }

        // ─────────────────────────────────────────────────────────────
        // Stage 5 — Trivy security scan (backend image)
        // Informational only — NEVER blocks the push to DockerHub
        // ─────────────────────────────────────────────────────────────
        stage('Trivy Security Scan') {
            steps {
                sh '''
                mkdir -p trivy-report

                echo "=== Disk space before Trivy scan ==="
                df -h /tmp

                # Run Trivy — exit-code 0 so it NEVER fails the build
                # Change to --exit-code 1 if you want to block on CRITICAL CVEs
                trivy image \
                    --exit-code 0 \
                    --severity CRITICAL,HIGH \
                    --no-progress \
                    --format table \
                    --output trivy-report/scan-${BUILD_NUMBER}.txt \
                    ${DOCKERHUB_REPO}:${IMAGE_TAG} || true

                echo "=== Trivy Scan Summary ==="
                if [ -f trivy-report/scan-${BUILD_NUMBER}.txt ]; then
                    cat trivy-report/scan-${BUILD_NUMBER}.txt
                else
                    echo "⚠️  Trivy scan report not generated (disk space or scan error) — continuing pipeline"
                fi
                '''
            }
        }

        // ─────────────────────────────────────────────────────────────
        // Stage 6 — Push both images to DockerHub
        // Requires Jenkins credential ID: dockerhub-credentials
        // ─────────────────────────────────────────────────────────────
        stage('Push to DockerHub') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'dockerhub-credentials',
                        usernameVariable: 'DOCKER_USER',
                        passwordVariable: 'DOCKER_PASS'
                    )
                ]) {
                    sh '''
                    echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin

                    # Push backend image
                    docker push ${DOCKERHUB_REPO}:${IMAGE_TAG}
                    docker push ${DOCKERHUB_REPO}:latest

                    # Push frontend image
                    docker push ${FRONTEND_REPO}:${IMAGE_TAG}
                    docker push ${FRONTEND_REPO}:latest

                    docker logout
                    '''
                }
            }
        }

        // ─────────────────────────────────────────────────────────────
        // Stage 7 — Deploy via Ansible
        // Jenkins calls ansible-playbook → kubernetes role applies all
        // K8s manifests (backend + frontend deployments, HPA, secrets).
        // K8s is NEVER touched directly from Jenkins — Ansible owns it.
        // ─────────────────────────────────────────────────────────────
        stage('Deploy') {
            steps {
                sh '''
                . venv/bin/activate
                echo "Triggering Ansible deployment for image tag: ${IMAGE_TAG}"
                ansible-playbook ansible/deploy.yml \
                    -i ansible/inventory/hosts.yml \
                    --extra-vars "image_tag=${IMAGE_TAG} frontend_tag=${IMAGE_TAG}" \
                    --vault-password-file /var/jenkins_home/.vault_pass
                '''
            }
        }
    }

    post {
        success {
            echo "✅ Pipeline PASSED — Image: ${DOCKERHUB_REPO}:${IMAGE_TAG}"
        }
        failure {
            echo "❌ Pipeline FAILED — Check logs above"
        }
        always {
            // Clean up dangling Docker images to save disk
            sh 'docker image prune -f || true'
            // Clean workspace to prevent accumulation of build files
            cleanWs()
        }
    }
}