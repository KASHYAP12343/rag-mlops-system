pipeline {

    agent any

    environment {
        GROQ_API_KEY = "dummy-ci-key"
    }

    stages {

        stage('Install Dependencies') {
            steps {
                sh '''
                python3 -m venv venv
                . venv/bin/activate
                pip install -r requirements-ci.txt
                '''
            }
        }

        stage('Run Tests') {
            steps {
                sh '''
                . venv/bin/activate
                pytest -v
                '''
            }
        }
    }

    post {
        success {
            echo 'Tests passed successfully!'
        }

        failure {
            echo 'Pipeline failed!'
        }
    }
}