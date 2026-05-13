pipeline {

    agent any

    environment {
        DOCKERHUB_REPO  = "mayank2101/rag-mlops"
        IMAGE_TAG       = "${env.BUILD_NUMBER}"
        GROQ_API_KEY    = "dummy-ci-key"
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
        // ─────────────────────────────────────────────────────────────
        stage('Build Docker Image') {
            steps {
                sh '''
                docker build \
                    --build-arg BUILD_NUMBER=${BUILD_NUMBER} \
                    -t ${DOCKERHUB_REPO}:${IMAGE_TAG} \
                    -t ${DOCKERHUB_REPO}:latest \
                    .
                '''
            }
        }

        // ─────────────────────────────────────────────────────────────
        // Stage 4 — Trivy security scan
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
        // Stage 5 — Push to DockerHub
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
                    docker push ${DOCKERHUB_REPO}:${IMAGE_TAG}
                    docker push ${DOCKERHUB_REPO}:latest
                    docker logout
                    '''
                }
            }
        }

        // ─────────────────────────────────────────────────────────────
        // Stage 6 — Deploy via Ansible
        // Triggers the Ansible deploy playbook after image is pushed
        // ─────────────────────────────────────────────────────────────
        stage('Deploy') {
            steps {
                sh '''
                echo "Triggering Ansible deployment for image tag: ${IMAGE_TAG}"
                ansible-playbook ansible/deploy.yml \
                    -i ansible/inventory/hosts.yml \
                    --extra-vars "image_tag=${IMAGE_TAG}" \
                    --vault-password-file /var/jenkins_home/.vault_pass \
                    || echo "Ansible not configured yet — skipping deploy"
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
        }
    }
}