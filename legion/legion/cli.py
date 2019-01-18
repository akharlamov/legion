#
#    Copyright 2019 EPAM Systems
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
#
"""
CLI logic for legion
"""
import argparse
import logging
import os
import stat
import sys
import time

import legion.config
import legion.containers.docker
import legion.containers.headers
import legion.k8s
import legion.edi.security
import legion.external.edi
import legion.external.grafana
import legion.pymodel
import legion.model
import legion.utils
import legion.template
from legion.utils import Colors, ExternalFileReader

LOGGER = logging.getLogger(__name__)

INSPECT_FORMAT_COLORIZED = 'colorized'
INSPECT_FORMAT_TABULAR = 'column'
VALID_INSPECT_FORMATS = INSPECT_FORMAT_COLORIZED, INSPECT_FORMAT_TABULAR


def build_model(args):
    """
    Build model

    :param args: command arguments
    :type args: :py:class:`argparse.Namespace`
    :return: :py:class:`docker.model.Image` docker image
    """
    client = legion.containers.docker.build_docker_client(args)

    model_file = args.model_file
    if not model_file:
        model_file = os.getenv(legion.config.MODEL_FILE[0])

    if not model_file:
        raise Exception('Model file has not been provided')

    with ExternalFileReader(model_file) as external_reader:
        if not os.path.exists(external_reader.path):
            raise Exception('Cannot find model binary {}'.format(external_reader.path))

        container = legion.pymodel.Model.load(external_reader.path)
        model_id = container.model_id
        model_version = container.model_version

        image_labels = legion.containers.docker.generate_docker_labels_for_image(external_reader.path, model_id, args)

        LOGGER.info('Building docker image...')

        new_image_tag = args.docker_image_tag
        if not new_image_tag:
            new_image_tag = 'legion-model-{}:{}.{}'.format(model_id, model_version, legion.utils.deduce_extra_version())

        image = legion.containers.docker.build_docker_image(
            client,
            model_id,
            external_reader.path,
            image_labels,
            new_image_tag
        )

        LOGGER.info('Image has been built: {}'.format(image))

        legion.utils.send_header_to_stderr(legion.containers.headers.IMAGE_ID_LOCAL, image.id)

        if image.tags:
            legion.utils.send_header_to_stderr(legion.containers.headers.IMAGE_TAG_LOCAL, image.tags[0])

        if args.push_to_registry:
            legion.containers.docker.push_image_to_registry(client, image, args.push_to_registry)

        return image


def inspect_kubernetes(args):
    """
    Inspect kubernetes

    :param args: command arguments with .namespace
    :type args: :py:class:`argparse.Namespace`
    :return: None
    """
    edi_client = legion.external.edi.build_client(args)
    LOGGER.info('Sending inspect request to {!r}'.format(edi_client))
    model_deployments = edi_client.inspect(args.model_id, args.model_version)

    data = []

    for deployment in model_deployments:
        if deployment.status == 'ok' and deployment.model_api_ok:
            line_color = Colors.OKGREEN
        elif deployment.status == 'warning':
            line_color = Colors.WARNING
        else:
            line_color = Colors.FAIL

        errors = ''

        if not deployment.model_api_ok:
            errors = 'MODEL API DOES NOT RESPOND'

        if errors:
            errors = 'ERROR: {}'.format(errors)

        data.append({
            'deployment': deployment,
            'errors': errors,
            'line_color': line_color
        })

    if args.format == INSPECT_FORMAT_COLORIZED:
        if data:
            print('%sModel deployments:%s' % (Colors.BOLD, Colors.ENDC))

            for item in data:
                arguments = (
                    item['line_color'], Colors.ENDC,
                    Colors.UNDERLINE, item['deployment'].model, Colors.ENDC,
                    item['deployment'].image, item['deployment'].version,
                    item['line_color'], item['deployment'].ready_replicas, item['deployment'].scale, item['errors'],
                    Colors.ENDC
                )
                print('%s*%s %s%s%s %s (version: %s) - %s%s / %d pods ready %s%s' % arguments)

        if not model_deployments:
            print('%s-- cannot find any model deployments --%s' % (Colors.WARNING, Colors.ENDC))

        if not data and model_deployments:
            print('%s-- cannot find any model deployments after filtering --%s' % (Colors.WARNING, Colors.ENDC))
    elif args.format == INSPECT_FORMAT_TABULAR:
        headers = 'Model ID', 'Image', 'Version', 'Ready', 'Scale', 'Errors'
        items = [[
            item['deployment'].model,
            item['deployment'].image,
            item['deployment'].version,
            str(item['deployment'].ready_replicas),
            str(item['deployment'].scale),
            item['errors'],
        ] for item in data]

        if data:
            columns_width = [max(len(val[col_idx]) for val in items) for col_idx, column in enumerate(headers)]
            columns_width = [max(columns_width[col_idx], len(column)) for col_idx, column in enumerate(headers)]

            print('|'. join('{name:{width}} '.format(name=column, width=columns_width[col_idx])
                            for col_idx, column in enumerate(headers)))
            for item in items:
                print('|'.join('{name:{width}} '.format(name=column, width=columns_width[col_idx])
                               for col_idx, column in enumerate(item)))


def get_related_model_deployments(client, affected_deployments):
    """
    Get actual status of model deployments

    :param client: EDI client
    :type client: :py:class:`legion.external.edi.EdiClient`
    :param affected_deployments: affected by main operation (e.g. deploy) model deployments
    :type affected_deployments: list[:py:class:`legion.containers.k8s.ModelDeploymentDescription`]
    :return: list[:py:class:`legion.containers.k8s.ModelDeploymentDescription`] -- actual status of model deployments
    """
    affected_deployment_ids = {
        deployment.id_and_version
        for deployment
        in affected_deployments
    }
    actual_deployments_status = client.inspect()
    LOGGER.debug('Filtering all models using affected deployment list')
    return [deploy
            for deploy in actual_deployments_status
            if deploy.id_and_version in affected_deployment_ids]


def wait_operation_finish(args, edi_client, model_deployments, wait_callback):
    """
    Wait operation to finish according command line arguments. Uses wait_callback for checking status

    :param args: command arguments with .model_id, .namespace
    :type args: :py:class:`argparse.Namespace`
    :param edi_client: EDI client instance
    :type edi_client: :py:class:`legion.external.edi.EdiClient`
    :param model_deployments: models that have been affected during operation call
    :type model_deployments: list[:py:class:`legion.containers.k8s.ModelDeploymentDescription`]
    :param wait_callback: function that will be called to ensure that operation completed (should return True)
    :type wait_callback: py:class:`Callable[[list[:py:class:`legion.containers.k8s.ModelDeploymentDescription`]],
                                            typing.Optional[bool]]`
    :return: None
    """
    if not args.no_wait:
        start = time.time()
        if args.timeout <= 0:
            raise Exception('Invalid --timeout argument: should be positive integer')

        LOGGER.debug('Starting checking cycle limited to {} s.'.format(args.timeout))

        while True:
            elapsed = time.time() - start
            if elapsed > args.timeout:
                raise Exception('Time out: operation has not been confirmed')

            LOGGER.info('Requesting actual status of affected deployments')
            affected_deployments_status = get_related_model_deployments(edi_client, model_deployments)
            LOGGER.debug('Server returned list of actual affected deployment statuses: {!r}'
                         .format(affected_deployments_status))

            result = wait_callback(affected_deployments_status)
            if result:
                LOGGER.info('Callback have confirmed completion of the operation')
                break
            else:
                LOGGER.info('Callback have not confirmed completion of the operation')

            LOGGER.debug('Sleep before next request')
            time.sleep(1)


def check_all_scaled(deployments_status, expected_scale, expected_count):
    """
    Check that all model finished scale process and now are OK

    :param deployments_status: actual deployment status
    :type deployments_status: list[:py:class:`legion.containers.k8s.ModelDeploymentDescription`]
    :param expected_scale: expected scale
    :type expected_scale: int
    :param expected_count: expected count of models
    :type expected_count: int
    :return: bool -- result of validation
    """
    # Get fully deployed models
    finally_deployed_models = [deployment
                               for deployment in deployments_status
                               if deployment.ready_replicas == expected_scale and deployment.model_api_ok]

    # Wait until all modes will be scaled
    return len(finally_deployed_models) == expected_count


def undeploy_kubernetes(args):
    """
    Undeploy model to kubernetes

    :param args: command arguments with .model_id, .namespace
    :type args: :py:class:`argparse.Namespace`
    :return: None
    """
    edi_client = legion.external.edi.build_client(args)
    LOGGER.info('Sending undeploy request to {!r}'.format(edi_client))
    model_deployments = edi_client.undeploy(args.model_id,
                                            args.grace_period,
                                            args.model_version,
                                            args.ignore_not_found)
    LOGGER.info('Server returned list of affected deployments: {!r}'.format(model_deployments))

    wait_operation_finish(args, edi_client,
                          model_deployments,
                          lambda affected_deployments_status: not affected_deployments_status)


def scale_kubernetes(args):
    """
    Scale model instances

    :param args: command arguments with .model_id, .namespace and .scale
    :type args: :py:class:`argparse.Namespace`
    :return: None
    """
    edi_client = legion.external.edi.build_client(args)
    LOGGER.info('Sending scale request to {!r}'.format(edi_client))
    model_deployments = edi_client.scale(args.model_id, args.scale, args.model_version)
    LOGGER.info('Server returned list of affected deployments: {!r}'.format(model_deployments))

    wait_operation_finish(args, edi_client,
                          model_deployments,
                          lambda affected_deployments_status: check_all_scaled(affected_deployments_status,
                                                                               args.scale,
                                                                               len(model_deployments)))


def deploy_kubernetes(args):
    """
    Deploy kubernetes model

    :param args: command arguments with .model_id, .namespace , .livenesstimeout,
                .readinesstimeout, .model_iam_role and .scale
    :type args: :py:class:`argparse.Namespace`
    :return: None
    """
    edi_client = legion.external.edi.build_client(args)
    LOGGER.info('Sending deploy request to {!r}'.format(edi_client))
    model_deployments = edi_client.deploy(args.image, args.model_iam_role, args.scale, args.livenesstimeout,
                                          args.readinesstimeout)
    LOGGER.info('Server returned list of affected deployments: {!r}'.format(model_deployments))

    wait_operation_finish(args, edi_client,
                          model_deployments,
                          lambda affected_deployments_status: check_all_scaled(affected_deployments_status,
                                                                               args.scale,
                                                                               len(model_deployments)))


def sandbox(args):
    """
    Create local sandbox
    It generates bash script to run sandbox


    :param args: command arguments with .image, .force_recreate
    :type args: :py:class:`argparse.Namespace`
    :return: None
    """
    work_directory = '/work-directory'

    local_fs_work_directory = os.path.abspath(os.getcwd())

    legion_data_directory = '/opt/legion/'
    model_file = 'model.bin'

    arguments = dict(
        local_fs=local_fs_work_directory,
        image=args.image,
        work_directory=work_directory,
        legion_data_directory=legion_data_directory,
        model_file=model_file
    )
    cmd = legion.utils.render_template('sandbox-cli.sh.tmpl', arguments)

    path_to_activate = os.path.abspath(os.path.join(os.getcwd(), 'legion-activate.sh'))

    if os.path.exists(path_to_activate) and not args.force_recreate:
        print('File {} already existed, ignoring creation of sandbox'.format(path_to_activate))
        return

    with open(path_to_activate, 'w') as activate_file:
        activate_file.write(cmd)

    current_mode = os.stat(path_to_activate)
    os.chmod(path_to_activate, current_mode.st_mode | stat.S_IEXEC)

    print('Sandbox has been created!')
    print('To activate run {!r} from command line'.format(path_to_activate))


def list_dependencies(args):
    """
    Print package dependencies

    :param args: command arguments
    :type args: :py:class:`argparse.Namespace`
    :return: None
    """
    dependencies = legion.utils.get_list_of_requirements()
    for name, version in dependencies:
        print('{}=={}'.format(name, version))


def configure_logging(args):
    """
    Set-up appropriate log level

    :param args: command arguments
    :type args: :py:class:`argparse.Namespace`
    :return: None
    """
    if args.verbose or legion.utils.string_to_bool(os.getenv('VERBOSE', '')):
        log_level = logging.DEBUG
    else:
        log_level = logging.ERROR

    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        stream=sys.stderr)

def build_parser():
    """
    Build parser for CLI

    :return: :py:class:`argparse.ArgumentParser` -- CLI parser for LegionCTL
    """
    parser = argparse.ArgumentParser(description='legion Command-Line Interface')
    parser.add_argument('--verbose',
                        help='verbose log output',
                        action='store_true')
    parser.add_argument('--version',
                        help='get package version',
                        action='store_true')
    subparsers = parser.add_subparsers()

    # --------- LOGIN SECTION -----------
    login_parser = subparsers.add_parser('login', description='Save edi credentials to the config')
    legion.edi.security.add_edi_arguments(login_parser, required=True)
    login_parser.set_defaults(func=legion.edi.security.login)

    # --------- LOCAL DOCKER SECTION -----------
    build_parser = subparsers.add_parser('build', description='build model into new docker image (should be run '
                                                              'in the docker container)')
    build_parser.add_argument('--model-file',
                              type=str, help='serialized model file name')
    build_parser.add_argument('--docker-image-tag',
                              type=str, help='docker image tag')
    build_parser.add_argument('--push-to-registry',
                              type=str, help='docker registry address')
    build_parser.set_defaults(func=build_model)

    # --------- KUBERNETES SECTION -----------
    deploy_k8s_parser = subparsers.add_parser('deploy',
                                              description='deploys a model into a kubernetes cluster')
    deploy_k8s_parser.add_argument('image',
                                   type=str, help='docker image')
    deploy_k8s_parser.add_argument('--local',
                                   action='store_true',
                                   help='deploy model locally. Incompatible with other arguments')
    deploy_k8s_parser.add_argument('--port',
                                   default=0,
                                   type=int, help='port to listen on. Only for --local mode')
    deploy_k8s_parser.add_argument('--model-iam-role',
                                   type=str, help='IAM role to be used at model pod')
    deploy_k8s_parser.add_argument('--scale',
                                   default=1,
                                   type=int, help='count of instances')
    deploy_k8s_parser.add_argument('--livenesstimeout',
                                   default=2,
                                   type=int, help='model startup timeout for liveness probe')
    deploy_k8s_parser.add_argument('--readinesstimeout',
                                   default=2,
                                   type=int, help='model startup timeout for readiness probe')
    legion.external.edi.add_arguments_for_wait_operation(deploy_k8s_parser)
    legion.edi.security.add_edi_arguments(deploy_k8s_parser)
    deploy_k8s_parser.set_defaults(func=deploy_kubernetes)

    inspect_k8s_parser = subparsers.add_parser('inspect',
                                               description='get information about currently deployed models')
    inspect_k8s_parser.add_argument('--model-id',
                                    type=str, help='model ID')
    inspect_k8s_parser.add_argument('--model-version',
                                    type=str, help='model version')
    inspect_k8s_parser.add_argument('--format',
                                    default=VALID_INSPECT_FORMATS[0],
                                    choices=VALID_INSPECT_FORMATS, help='output format')
    inspect_k8s_parser.add_argument('--local',
                                    action='store_true',
                                    help='analyze local deployed models')
    legion.edi.security.add_edi_arguments(inspect_k8s_parser)
    inspect_k8s_parser.set_defaults(func=inspect_kubernetes)

    scale_k8s_parser = subparsers.add_parser('scale',
                                             description='change count of model pods')
    scale_k8s_parser.add_argument('model_id',
                                  type=str, help='model ID')
    scale_k8s_parser.add_argument('scale',
                                  type=int, help='new count of replicas')
    scale_k8s_parser.add_argument('--model-version',
                                  type=str, help='model version')
    legion.external.edi.add_arguments_for_wait_operation(scale_k8s_parser)
    legion.edi.security.add_edi_arguments(scale_k8s_parser)
    scale_k8s_parser.set_defaults(func=scale_kubernetes)

    undeploy_k8s_parser = subparsers.add_parser('undeploy',
                                                description='undeploy model deployment')
    undeploy_k8s_parser.add_argument('model_id',
                                     type=str, help='model ID')
    undeploy_k8s_parser.add_argument('--model-version',
                                     type=str, help='model version')
    undeploy_k8s_parser.add_argument('--grace-period',
                                     default=0,
                                     type=int, help='removal grace period')
    undeploy_k8s_parser.add_argument('--ignore-not-found',
                                     action='store_true', help='ignore if cannot found pod')
    undeploy_k8s_parser.add_argument('--local',
                                     action='store_true',
                                     help='un-deploy local deployed model. Incompatible with --grace-period')
    legion.external.edi.add_arguments_for_wait_operation(undeploy_k8s_parser)
    legion.edi.security.add_edi_arguments(undeploy_k8s_parser)
    undeploy_k8s_parser.set_defaults(func=undeploy_kubernetes)

    # --------- SERVING SECTION -----------
    pyserve_parser = subparsers.add_parser('pyserve', description='serve a python model')
    pyserve_parser.add_argument('--model_file',
                                type=str)
    pyserve_parser.add_argument('--model-id',
                                type=str)
    pyserve_parser.add_argument('--legion-addr',
                                type=str)
    pyserve_parser.add_argument('--legion-port',
                                type=int)
    pyserve_parser.add_argument('--debug',
                                type=legion.utils.string_to_bool)
    pyserve_parser.set_defaults(func=legion.serving.pyserve.serve_model)

    # --------- LOCAL SECTION -----------
    sandbox_parser = subparsers.add_parser('create-sandbox', description='create sandbox')
    sandbox_parser.add_argument('--image',
                                type=str,
                                default=os.getenv('LEGION_TOOLCHAIN',
                                                  'legionplatform/python-toolchain:' + legion.__version__),
                                help='explicitly set toolchain python image')
    sandbox_parser.add_argument('--force-recreate',
                                action='store_true',
                                help='recreate sandbox if it already existed')
    sandbox_parser.add_argument('rest',
                                nargs=argparse.REMAINDER)
    sandbox_parser.set_defaults(func=sandbox)

    # --------- UTILS SECTION -----------
    list_dependencies_parser = subparsers.add_parser('list-dependencies', description='list package dependencies')
    list_dependencies_parser.set_defaults(func=list_dependencies)

    # --------- END OF SECTIONS -----------

    return parser
