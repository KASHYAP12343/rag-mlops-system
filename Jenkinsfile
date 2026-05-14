pipeline {

    agent any

    // ── Keep only last 5 builds & 10 days of history to prevent disk bloat ──
    options {
        buildDiscarder(logRotator(numToKeepStr: '5', daysToKeepStr: '10', artifactNumToKeepStr: '3'))
        timestamps()
        // Kill the entire pipeline if it runs longer than 90 minutes —
        // First-time full push (cold DockerHub layer cache) can take ~60 min.
        // Subsequent builds are fast (1-2 min) as layers are cached on DockerHub.
        timeout(time: 90, unit: 'MINUTES')
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
                mkdir -p test-results
                pytest -v --tb=short --junitxml=test-results/results.xml
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
                # Prune dangling (untagged) images to free disk before building
                docker image prune -f || true

                echo "=== Disk space before backend build ==="
                df -h /

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
            // Retry up to 3 times — large torch/model layers can time out on
            // slow or congested networks. Each retry resumes from where it left off
            // because Docker reuses already-uploaded layers.
            options { retry(3) }
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

                    # Push with retry — retries only on failure, does NOT push again
                    # on success (fixed bug: old version called docker push unconditionally
                    # after the loop even when the loop had already succeeded).
                    push_with_retry() {
                        local image=$1
                        local max=3
                        local attempt=1
                        while [ $attempt -le $max ]; do
                            echo "Pushing $image (attempt $attempt/$max)..."
                            if docker push "$image"; then
                                echo "✅ Push succeeded for $image"
                                return 0
                            fi
                            echo "⚠️  Push failed for $image — retry $attempt/$max in 15s..."
                            attempt=$((attempt + 1))
                            sleep 15
                        done
                        echo "❌ Push failed after $max attempts for $image"
                        return 1
                    }

                    push_with_retry ${DOCKERHUB_REPO}:${IMAGE_TAG}
                    push_with_retry ${DOCKERHUB_REPO}:latest

                    # Push frontend image
                    push_with_retry ${FRONTEND_REPO}:${IMAGE_TAG}
                    push_with_retry ${FRONTEND_REPO}:latest

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
                export KUBECONFIG=/var/jenkins_home/.kube/config
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