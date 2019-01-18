#
#    Copyright 2017 EPAM Systems
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
import argparse
import contextlib
import os
import io
import sys
import logging
import requests

import unittest2

import legion.cli
import legion.utils

# Extend PYTHONPATH in order to import test tools and models
sys.path.extend(os.path.dirname(__file__))

from legion_test_utils import ModelLocalContainerExecutionContext, build_distribution, \
    ModelDockerBuilderContainerContext, gather_stdout_stderr, ManagedProcessContext


def build_activate_script_path(root):
    """
    Build activate script path

    :param root:
    :return:
    """
    return os.path.abspath(os.path.join(root, 'legion-activate.sh'))


def lookup_for_parser_defaults(parser_name):
    """
    Get default values for parser

    :param parser_name: name of parser, e.g. login
    :type parser_name: str
    :return: :py:class:`argparse.Namespace` -- default values
    """
    _, subparsers = legion.cli.build_parser()

    parser = subparsers.choices.get(parser_name, None)
    if not parser:
        raise Exception('Cannot find parser for command {!r}'.format(parser_name))

    args = parser.parse_args([])
    return args


class TestLocalRun(unittest2.TestCase):
    _multiprocess_shared_ = True

    @classmethod
    def setUpClass(cls):
        """
        Enable logs on tests start, setup connection context

        :return: None
        """
        logging.basicConfig(level=logging.DEBUG)

    def test_create_env(self):
        with legion.utils.TemporaryFolder(change_cwd=True) as tempfs:
            create_sandbox_args = lookup_for_parser_defaults('create-sandbox')
            legion.cli.sandbox(create_sandbox_args)

            desired_path = build_activate_script_path(tempfs.path)
            self.assertTrue(os.path.exists(desired_path), 'File {} does not exist'.format(desired_path))

    def test_recreate_env(self):
        with legion.utils.TemporaryFolder(change_cwd=True) as tempfs:
            create_sandbox_args = lookup_for_parser_defaults('create-sandbox')
            legion.cli.sandbox(create_sandbox_args)

            desired_path = build_activate_script_path(tempfs.path)
            self.assertTrue(os.path.exists(desired_path), 'File {} does not exist'.format(desired_path))

            with gather_stdout_stderr() as (stdout, _):
                create_sandbox_args = lookup_for_parser_defaults('create-sandbox')
                create_sandbox_args.force_recreate = True
                legion.cli.sandbox(create_sandbox_args)
                self.assertNotIn('already existed', stdout.getvalue())
                self.assertNotIn('ignoring creation of sandbox', stdout.getvalue())

                self.assertIn('Sandbox has been created!', stdout.getvalue())
                self.assertIn('To activate run', stdout.getvalue())

    def test_recreate_env_negative(self):
        with legion.utils.TemporaryFolder(change_cwd=True) as tempfs:
            create_sandbox_args = lookup_for_parser_defaults('create-sandbox')
            legion.cli.sandbox(create_sandbox_args)

            desired_path = build_activate_script_path(tempfs.path)
            self.assertTrue(os.path.exists(desired_path), 'File {} does not exist'.format(desired_path))

            with gather_stdout_stderr() as (stdout, _):
                create_sandbox_args = lookup_for_parser_defaults('create-sandbox')
                legion.cli.sandbox(create_sandbox_args)
                self.assertIn('already existed', stdout.getvalue())
                self.assertIn('ignoring creation of sandbox', stdout.getvalue())

                self.assertNotIn('Sandbox has been created!', stdout.getvalue())
                self.assertNotIn('To activate run', stdout.getvalue())

    def test_activate_file_permissions(self):
        with legion.utils.TemporaryFolder(change_cwd=True) as tempfs:
            create_sandbox_args = lookup_for_parser_defaults('create-sandbox')
            legion.cli.sandbox(create_sandbox_args)

            desired_path = build_activate_script_path(tempfs.path)
            self.assertTrue(os.path.exists(desired_path), 'File {} does not exist'.format(desired_path))

            permission = os.stat(desired_path).st_mode
            print('Activate file has access permission: {0:o}'.format(permission))
            self.assertEqual(permission & 0o777, 0o744, 'Activate file has wrong permission')

    def test_activate_file_content(self):
        with legion.utils.TemporaryFolder(change_cwd=True) as tempfs:
            create_sandbox_args = lookup_for_parser_defaults('create-sandbox')
            legion.cli.sandbox(create_sandbox_args)

            desired_path = build_activate_script_path(tempfs.path)
            self.assertTrue(os.path.exists(desired_path), 'File {} does not exist'.format(desired_path))

            with open(desired_path, 'r') as stream:
                content = stream.read()

            self.assertTrue(content.startswith('#!/usr/bin/env bash'), 'Shebang does not found')
            self.assertIn('docker run -ti --rm ', content, 'Docker run with -ti and --rm not found')

    def test_enter_exit_sandbox(self):
        with legion.utils.TemporaryFolder(change_cwd=True) as tempfs:
            create_sandbox_args = lookup_for_parser_defaults('create-sandbox')
            legion.cli.sandbox(create_sandbox_args)

            desired_path = build_activate_script_path(tempfs.path)

            with ManagedProcessContext([desired_path], shell=True) as context:
                a, b = context.stdout, context.stderr
                x = 20





    # def test_summation_model_build_and_query(self):
    #     with ModelDockerBuilderContainerContext() as context:
    #         context.copy_model('summation_model')
    #         model_id, model_version, model_file, _ = context.execute_model()
    #         self.assertEqual(model_id, 'test-summation', 'incorrect model id')
    #         self.assertEqual(model_version, '1.0', 'incorrect model version')
    #         self.assertIsNotNone(model_file)
    #         image_id, _ = context.build_model_container()
    #
    #     with ModelLocalContainerExecutionContext(image_id) as context:
    #         self.assertDictEqual(context.model_information, {
    #             'endpoints': {
    #                 'default': {
    #                     'input_params': False,
    #                     'name': 'default',
    #                     'use_df': False,
    #                 }
    #             },
    #             'model_id': model_id,
    #             'model_version': model_version
    #         }, 'invalid model information')
    #
    #         self.assertEqual(context.client.invoke(a=10, b=20)['result'], 30, 'invalid invocation result')
    #         self.assertListEqual(
    #             context.client.batch([{'a': 10, 'b': 10}, {'a': 20, 'b': 30}]),
    #             [
    #                 {
    #                     'result': 20,
    #                 },
    #                 {
    #                     'result': 50,
    #                 }
    #             ],
    #             'invalid batch invocation result'
    #         )



if __name__ == '__main__':
    unittest2.main()
