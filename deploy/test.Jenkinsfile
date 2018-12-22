pipeline {
    agent any

    environment {
        //Input parameters
        param_string = "${params.StrParam}"
        param_bool_true = "${params.BoolParamTrue}"
        param_bool_false = "${params.BoolParamFalse}"
    }

    stages {
        stage('stage 1') {
            steps {
                script {
                    print(env.param_string.getClass())
                    print(env.param_bool_true.getClass())
                    print(env.param_bool_false.getClass())
                    if ( env.param_bool_true == "true") {
                        print("true check")
                        print("true: ${env.param_bool_true}")
                        print("false: ${env.param_bool_false}")
                    } else {
                        print("true is not false")
                    }
                    if ( env.param_string) {
                        print("string is true")
                        print("true: ${env.param_bool_true}")
                        print("string: ${env.param_string}")
                    } else {
                        print("string is not true")
                    }
                }
            }
        }

    }
    
    post {
        always {
            deleteDir()
        }
    }
}