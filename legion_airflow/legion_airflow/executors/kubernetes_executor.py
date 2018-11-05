#
#   Copyright 2018 EPAM Systems
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
"""
Customized Kubernetes Executors.
"""

from airflow.contrib.executors import kubernetes_executor as ke
from airflow.executors import Executors


class LegionKubernetesExecutorConfig(ke.KubernetesExecutorConfig):
    """
    LegionKubernetesExecutorConfig adds annotations support to KubernetesExecutorConfig.
    """

    def __init__(self, annotations=None, *args, **kwargs):
        """
        Init LegionKubernetesExecutorConfig object
        :param annotations: pod annotations
        """
        super(LegionKubernetesExecutorConfig, self).__init__(*args, **kwargs)
        self.annotations = annotations

    @staticmethod
    def from_dict(obj):
        """
        Create LegionKubernetesExecutorConfig from dict
        :param obj: dict with parameters values
        :return: executor config object
        """
        if obj is None:
            return LegionKubernetesExecutorConfig()

        if not isinstance(obj, dict):
            raise TypeError(
                'Cannot convert a non-dictionary object into a LegionKubernetesExecutorConfig')

        namespaced = obj.get(Executors.KubernetesExecutor, {})

        return LegionKubernetesExecutorConfig(
            image=namespaced.get('image', None),
            image_pull_policy=namespaced.get('image_pull_policy', None),
            request_memory=namespaced.get('request_memory', None),
            request_cpu=namespaced.get('request_cpu', None),
            limit_memory=namespaced.get('limit_memory', None),
            limit_cpu=namespaced.get('limit_cpu', None),
            gcp_service_account_key=namespaced.get('gcp_service_account_key', None),
            node_selectors=namespaced.get('node_selectors', None),
            affinity=namespaced.get('affinity', None),
            annotations=namespaced.get('annotations', {}),
        )


class LegionKubernetesExecutor(ke.KubernetesExecutor):
    """
    LegionKubernetesExecutor adds annotations support to KubernetesExecutor.
    """

    def execute_async(self, key, command, queue=None, executor_config=None):
        """
        Execute aync task
        :param key: Task key
        :param command: Task command
        :param queue: Queue object
        :param executor_config: Executor config object
        :return:
        """
        self.log.info(
            'Add task %s with command %s with executor_config %s',
            key, command, executor_config
        )
        kube_executor_config = LegionKubernetesExecutorConfig.from_dict(executor_config)
        self.task_queue.put((key, command, kube_executor_config))
