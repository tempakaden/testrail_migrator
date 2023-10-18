# TestY TMS - Test Management System
# Copyright (C) 2023 KNS Group LLC (YADRO)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Also add information on how to contact you by electronic and paper mail.
#
# If your software can interact with users remotely through a computer
# network, you should also make sure that it provides a way for users to
# get its source.  For example, if your program is a web application, its
# interface could display a "Source" link that leads users to an archive
# of the code.  There are many ways you could offer source, and different
# solutions will be better for different programs; see section 13 for the
# specific requirements.
#
# You should also get your employer (if you work as a programmer) or school,
# if any, to sign a "copyright disclaimer" for the program, if necessary.
# For more information on this, and how to apply and follow the GNU AGPL, see
# <http://www.gnu.org/licenses/>.
import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Dict

import redis
from asgiref.sync import async_to_sync
from celery import shared_task
from core.models import Project
from django.conf import settings
from django.db import transaction
from testrail_migrator.migrator_lib import TestRailClient, TestrailConfig, TestyCreator
from testrail_migrator.migrator_lib.migrator_service import MigratorService
from testrail_migrator.migrator_lib.testrail import InstanceType
from testrail_migrator.migrator_lib.testy import ParentType
from testrail_migrator.models import TestrailBackup
from tests_description.models import TestCase, TestCaseStep
from tests_representation.models import TestResult
from tests_representation.services.results import TestResultService

from utils import ProgressRecorderContext


def get_fake_mapping_for_steps(case_mappings):
    ids = TestCaseStep.objects.filter(test_case__in=case_mappings.values()).values_list('id', flat=True)
    return dict(zip(ids, ids))


@shared_task(bind=True)
def upload_task(self, backup_name, config_dict, upload_root_runs: bool, service_user_login='admin',
                testy_attachment_url: str = None, testy_project_id=None):
    progress_recorder = ProgressRecorderContext(self, total=22, description='Upload started')
    with transaction.atomic():
        logging.info('redis about to start')
        redis_client = redis.StrictRedis(settings.REDIS_HOST, settings.REDIS_PORT)
        logging.info('redis started')
        backup = json.loads(redis_client.get(backup_name))

        custom_fields_multi_select = parse_multi_select_from_tr(backup['custom_result_fields'])
        custom_fields_labels = parse_labels_from_tr_fields(backup['custom_result_fields'])

        creator = TestyCreator(service_user_login, testy_attachment_url)

        mappings = {}
        if testy_project_id:
            project = Project.objects.get(pk=testy_project_id)
        else:
            with progress_recorder.progress_context('Creating projects'):
                project = MigratorService.create_project(backup['project'])

        with progress_recorder.progress_context('Creating users'):
            mappings['users'] = creator.create_users(backup['users'])

        keys_without_mappings = ['suites', 'configs', 'milestones']
        for key in keys_without_mappings:
            with progress_recorder.progress_context(f'Creating {key}'):
                create_method = getattr(creator, f'create_{key}')
                mappings[key] = create_method(backup[key], project.id)

        keys_with_single_mapping = [('sections', 'suites'), ('plans', 'milestones')]
        for key, mapping_key in keys_with_single_mapping:
            with progress_recorder.progress_context(f'Creating {key}'):
                create_method = getattr(creator, f'create_{key}')
                mappings[key] = create_method(backup[key], mappings[mapping_key], project.id)

        with progress_recorder.progress_context('Creating cases'):
            mappings['cases'] = creator.create_cases(backup['cases'], mappings['suites'], mappings['sections'],
                                                     project.id, config_dict['custom_fields_matcher'])

        with progress_recorder.progress_context('Creating runs with plan as parent'):
            mappings['tests_parent_plan'], mappings['runs_parent_plan'] = creator.create_runs(
                runs=backup['runs_parent_plan'],
                mapping=mappings['plans'],
                config_mappings=mappings['configs'],
                tests=backup['tests_parent_plan'],
                case_mappings=mappings['cases'],
                project_id=project.id,
                upload_root_runs=upload_root_runs,
                parent_type=ParentType.PLAN,
                user_mappings=mappings['users']
            )

        with progress_recorder.progress_context('Creating results with plan as parent'):
            mappings['results_parent_plan'] = creator.create_results(
                backup['results_parent_plan'],
                custom_fields_multi_select,
                custom_fields_labels,
                mappings['tests_parent_plan'],
                mappings['users']
            )

        with progress_recorder.progress_context('Creating runs with mile as parent'):
            mappings['tests_parent_mile'], mappings['runs_parent_mile'] = creator.create_runs(
                runs=backup['runs_parent_mile'],
                mapping=mappings['milestones'],
                config_mappings=mappings['configs'],
                tests=backup['tests_parent_mile'],
                case_mappings=mappings['cases'],
                project_id=project.id,
                upload_root_runs=upload_root_runs,
                parent_type=ParentType.MILESTONE,
                user_mappings=mappings['users']
            )

        with progress_recorder.progress_context('Creating runs with mile as parent'):
            mappings['results_parent_mile'] = creator.create_results(
                backup['results_parent_mile'],
                custom_fields_multi_select,
                custom_fields_labels,
                mappings['tests_parent_mile'],
                mappings['users'],
            )
        if not backup.get('attachments'):
            return
        mappings['attachments'] = {}
        keys = [
            ('cases', 'case_id', InstanceType.CASE),
            ('plans', 'plan_id', InstanceType.PLAN),
            ('runs_parent_plan', 'run_id', InstanceType.RUN),
            ('runs_parent_mile', 'run_id', InstanceType.RUN),
        ]

        testrail_client = TestRailClient(TestrailConfig(**config_dict))

        for key, parent_key, instance_type in keys:
            with progress_recorder.progress_context(f'Creating attachments for {key}'):
                file_attachments = testrail_client.get_attachments_from_list(backup['attachments'][key], parent_key)
                mappings['attachments'].update(
                    creator.attachment_bulk_create(file_attachments, project, mappings['users'], parent_key,
                                                   mappings[key], instance_type)
                )

        keys = [
            ('parent_plan', 'result_id', InstanceType.TEST),
            ('parent_mile', 'result_id', InstanceType.TEST)
        ]

        for key, parent_key, instance_type in keys:
            with progress_recorder.progress_context(f'Creating attachments for {key}'):
                file_attachments = testrail_client.get_attachments_from_list(
                    backup['attachments'][f'tests_{key}'],
                    parent_key
                )
                mappings['attachments'].update(
                    creator.attachment_bulk_create(file_attachments, project, mappings['users'], parent_key,
                                                   mappings[f'results_{key}'], instance_type)
                )

        mappings['steps'] = get_fake_mapping_for_steps(mappings['cases'])
        mappings_keys = [
            ('cases', TestCase, MigratorService.case_update, ['scenario', 'setup', 'description']),
            ('steps', TestCaseStep, MigratorService.step_update, ['scenario', 'expected']),
            ('results_parent_mile', TestResult, TestResultService().result_update, ['comment']),
            ('results_parent_plan', TestResult, TestResultService().result_update, ['comment']),
        ]

        for mapping_key, model_class, update_method, field_list in mappings_keys:
            with progress_recorder.progress_context(f'Looking for attachments in fields of {mapping_key}'):
                creator.update_testy_attachment_urls_async(
                    mappings[mapping_key],
                    model_class,
                    update_method,
                    field_list,
                    config_dict,
                    mappings['attachments']
                )


@shared_task(bind=True)
def upload_suites_task(self, backup_name, config_dict, testy_project_id, service_user_login='admin',
                       testy_attachment_url: str = None):
    progress_recorder = ProgressRecorderContext(self, total=7, description='Upload started')
    with transaction.atomic():
        logging.info('redis about to start')
        redis_client = redis.StrictRedis(settings.REDIS_HOST, settings.REDIS_PORT)
        logging.info('redis started')
        backup = json.loads(redis_client.get(backup_name))

        creator = TestyCreator(service_user_login, testy_attachment_url)

        mappings = {}

        with progress_recorder.progress_context('Creating users'):
            mappings['users'] = creator.create_users(backup['users'])

        with progress_recorder.progress_context('Creating suites'):
            mappings['suites'] = creator.create_suites(backup['suites'], testy_project_id)

        with progress_recorder.progress_context('Creating sections'):
            mappings['sections'] = creator.create_sections(backup['sections'], mappings['suites'], testy_project_id)

        with progress_recorder.progress_context('Creating cases'):
            mappings['cases'] = creator.create_cases(
                backup['cases'],
                mappings['suites'],
                mappings['sections'],
                testy_project_id,
                config_dict['custom_fields_matcher']
            )
        if not backup.get('attachments'):
            return
        mappings['attachments'] = {}

        testrail_client = TestRailClient(TestrailConfig(**config_dict))

        with progress_recorder.progress_context('Creating attachments for cases'):
            file_attachments = testrail_client.get_attachments_from_list(backup['attachments']['cases'], 'case_id')
            mappings['attachments'].update(
                creator.attachment_bulk_create(file_attachments, Project.objects.get(pk=testy_project_id),
                                               mappings['users'], 'case_id',
                                               mappings['cases'], InstanceType.CASE)
            )

        with progress_recorder.progress_context('Looking for attachments in fields of cases'):
            creator.update_testy_attachment_urls_async(
                mappings['cases'],
                TestCase,
                MigratorService.case_update,
                ['scenario', 'setup', 'description'],
                config_dict,
                mappings['attachments']
            )

        with progress_recorder.progress_context('Looking for attachments in fields of cases'):
            mappings['steps'] = get_fake_mapping_for_steps(mappings['cases'])
            creator.update_testy_attachment_urls_async(
                mappings['steps'],
                TestCaseStep,
                MigratorService.step_update,
                ['scenario', 'expected'],
                config_dict,
                mappings['attachments']
            )


@shared_task(bind=True)
def download_task(self, project_id: int, config_dict: Dict, download_attachments, ignore_completed, backup_filename):
    progress_recorder = ProgressRecorderContext(self, total=21, description='Download started')

    resulting_data = {}

    testrail_client = TestRailClient(TestrailConfig(**config_dict))
    with progress_recorder.progress_context('Getting users'):
        resulting_data['users'] = testrail_client.get_users()
    with progress_recorder.progress_context('Getting custom fields for results '):
        resulting_data['custom_result_fields'] = testrail_client.get_custom_result_fields()
    with progress_recorder.progress_context('Getting project'):
        resulting_data['project'] = testrail_client.get_project(project_id)
    with progress_recorder.progress_context('Getting suites'):
        resulting_data['suites'] = testrail_client.get_suites(project_id)
    with progress_recorder.progress_context('Getting cases'):
        resulting_data['cases'] = testrail_client.get_cases(project_id, resulting_data['suites'])
    with progress_recorder.progress_context('Getting sections'):
        resulting_data['sections'] = testrail_client.get_sections(project_id, resulting_data['suites'])

    query_params = {'is_completed': 0} if ignore_completed else None
    with progress_recorder.progress_context('Getting configs'):
        resulting_data['configs'] = testrail_client.get_configs(project_id)
    with progress_recorder.progress_context('Getting milestones'):
        resulting_data['milestones'] = testrail_client.get_milestones(project_id, ignore_completed, query_params)
    with progress_recorder.progress_context('Getting plans'):
        resulting_data['plans'] = testrail_client.get_plans_with_runs(project_id, query_params)
    with progress_recorder.progress_context('Getting runs for plans'):
        resulting_data['runs_parent_plan'] = testrail_client.get_runs_from_plans(resulting_data['plans'])
    with progress_recorder.progress_context('Getting runs for milestones'):
        resulting_data['runs_parent_mile'] = testrail_client.get_runs(project_id, query_params=query_params)
    with progress_recorder.progress_context('Getting tests for runs from plans'):
        resulting_data['tests_parent_plan'] = testrail_client.get_tests_for_runs(resulting_data['runs_parent_plan'])
    with progress_recorder.progress_context('Getting tests for runs from miles'):
        resulting_data['tests_parent_mile'] = testrail_client.get_tests_for_runs(resulting_data['runs_parent_mile'])
    with progress_recorder.progress_context('Getting results for tests from plans'):
        resulting_data['results_parent_plan'] = testrail_client.get_results_for_tests(
            resulting_data['tests_parent_plan']
        )
    with progress_recorder.progress_context('Getting results for tests from milestones'):
        resulting_data['results_parent_mile'] = testrail_client.get_results_for_tests(
            resulting_data['tests_parent_mile']
        )
    if not download_attachments:
        save_results_to_redis(resulting_data, backup_filename)
        return
    keys_instance_type = [
        ('cases', InstanceType.CASE),
        ('plans', InstanceType.PLAN),
        ('runs_parent_mile', InstanceType.RUN),
        ('runs_parent_plan', InstanceType.RUN),
        ('tests_parent_mile', InstanceType.TEST),
        ('tests_parent_plan', InstanceType.TEST)
    ]
    resulting_data['attachments'] = {}

    for key, instance_type in keys_instance_type:
        with progress_recorder.progress_context(f'Getting attachments for {key}'):
            resulting_data['attachments'][key] = testrail_client.get_attachments_for_instances(
                resulting_data[key],
                instance_type
            )
    print(f'SUMMARY OF STEPS {progress_recorder.current}')
    save_results_to_redis(resulting_data, backup_filename)


@shared_task(bind=True)
def download_milestone_task(
        self,
        project_id: int,
        milestone_ids,
        config_dict: Dict,
        download_attachments,
        ignore_completed,
        backup_filename
):
    query_params = {'milestone_id': ','.join(map(str, milestone_ids))}
    resulting_data = {}
    if ignore_completed:
        query_params['is_completed'] = 0
    progress_recorder = ProgressRecorderContext(self, total=14, description='Download started')
    testrail_client = TestRailClient(TestrailConfig(**config_dict))
    with progress_recorder.progress_context('Getting users'):
        resulting_data['users'] = testrail_client.get_users()
    with progress_recorder.progress_context('Getting custom fields for results '):
        resulting_data['custom_result_fields'] = testrail_client.get_custom_result_fields()
    with progress_recorder.progress_context('Getting configs'):
        resulting_data['configs'] = testrail_client.get_configs(project_id)

    with progress_recorder.progress_context('Getting milestones'):
        resulting_data['milestones'] = []

        for milestone_id in milestone_ids:
            milestone = testrail_client.get_milestone(milestone_id)
            if milestone['parent_id'] in milestone_ids:
                continue
            resulting_data['milestones'].append(milestone)
    with progress_recorder.progress_context('Getting plans'):
        resulting_data['plans'] = testrail_client.get_plans_with_runs(project_id, query_params)
    with progress_recorder.progress_context('Getting runs'):
        resulting_data['runs_parent_mile'] = testrail_client.get_runs(project_id, query_params)
        for milestone in resulting_data['milestones']:
            for child_milestone in milestone['milestones']:
                query_params['milestone_id'] = child_milestone['id']
                resulting_data['plans'].extend(testrail_client.get_plans_with_runs(project_id, query_params))
                resulting_data['runs_parent_mile'].extend(testrail_client.get_runs(project_id, query_params))

        resulting_data['runs_parent_plan'] = testrail_client.get_runs_from_plans(resulting_data['plans'])

    with progress_recorder.progress_context('Getting suites'):
        found_suite_ids = []
        for key in ['runs_parent_plan', 'runs_parent_mile']:
            for elem in resulting_data[key]:
                found_suite_ids.append(elem['suite_id'])
        found_suite_ids = set(found_suite_ids)
        resulting_data['suites'] = []
        for suite in testrail_client.get_suites(project_id):
            if suite['id'] in found_suite_ids:
                resulting_data['suites'].append(suite)

    with progress_recorder.progress_context('Getting cases'):
        resulting_data['cases'] = testrail_client.get_cases(project_id, resulting_data['suites'])
    with progress_recorder.progress_context('Getting sections'):
        resulting_data['sections'] = testrail_client.get_sections(project_id, resulting_data['suites'])
    with progress_recorder.progress_context('Getting tests'):
        resulting_data['tests_parent_plan'] = testrail_client.get_tests_for_runs(resulting_data['runs_parent_plan'])
        resulting_data['tests_parent_mile'] = testrail_client.get_tests_for_runs(resulting_data['runs_parent_mile'])
        found_cases = []

        for key in ['tests_parent_plan', 'tests_parent_mile']:
            for elem in resulting_data[key]:
                found_cases.append(elem['case_id'])
        found_cases = set(found_cases)
        cases = []
        for idx, case in enumerate(resulting_data['cases']):
            if case['id'] in found_cases:
                cases.append(case)
        resulting_data['cases'] = cases

    with progress_recorder.progress_context('Getting results'):
        resulting_data['results_parent_plan'] = testrail_client.get_results_for_tests(
            resulting_data['tests_parent_plan']
        )
        resulting_data['results_parent_mile'] = testrail_client.get_results_for_tests(
            resulting_data['tests_parent_mile']
        )

    if not download_attachments:
        save_results_to_redis(resulting_data, backup_filename)
        return

    with progress_recorder.progress_context('Getting attachments'):
        keys_instance_type = [
            ('cases', InstanceType.CASE),
            ('plans', InstanceType.PLAN),
            ('runs_parent_mile', InstanceType.RUN),
            ('runs_parent_plan', InstanceType.RUN),
            ('tests_parent_mile', InstanceType.TEST),
            ('tests_parent_plan', InstanceType.TEST)
        ]
        resulting_data['attachments'] = {}

        for key, instance_type in keys_instance_type:
            resulting_data['attachments'][key] = testrail_client.get_attachments_for_instances(
                resulting_data[key],
                instance_type
            )
    save_results_to_redis(resulting_data, backup_filename)


@shared_task(bind=True)
def download_suites_task(self, project_id: int, config_dict: Dict, download_attachments, backup_filename, suite_ids):
    progress_recorder = ProgressRecorderContext(self, total=5, description='Download started')

    resulting_data = {}

    testrail_client = TestRailClient(TestrailConfig(**config_dict))

    with progress_recorder.progress_context('Getting users'):
        resulting_data['users'] = testrail_client.get_users()
    with progress_recorder.progress_context('Getting suites'):
        resulting_data['suites'] = testrail_client.get_suites(project_id)
        resulting_data['suites'] = [elem for elem in resulting_data['suites'] if elem['id'] in suite_ids]
    with progress_recorder.progress_context('Getting cases'):
        resulting_data['cases'] = testrail_client.get_cases(project_id, resulting_data['suites'])
    with progress_recorder.progress_context('Getting sections'):
        resulting_data['sections'] = testrail_client.get_sections(project_id, resulting_data['suites'])
    if not download_attachments:
        save_results_to_redis(resulting_data, backup_filename)
        return
    resulting_data['attachments'] = {}
    with progress_recorder.progress_context('Getting attachments for cases'):
        resulting_data['attachments']['cases'] = testrail_client.get_attachments_for_instances(
            resulting_data['cases'],
            InstanceType.CASE
        )
    print(f'SUMMARY OF STEPS {progress_recorder.current}')
    save_results_to_redis(resulting_data, backup_filename)


@shared_task(bind=True)
def download_plans_runs_task(self, project_id: int, config_dict: Dict, download_attachments, backup_filename, plans_ids,
                             runs_ids):
    resulting_data = {}
    progress_recorder = ProgressRecorderContext(self, total=11, description='Download started')
    testrail_client = TestRailClient(TestrailConfig(**config_dict))
    with progress_recorder.progress_context('Getting users'):
        resulting_data['users'] = testrail_client.get_users()
    with progress_recorder.progress_context('Getting custom fields for results '):
        resulting_data['custom_result_fields'] = testrail_client.get_custom_result_fields()
    with progress_recorder.progress_context('Getting configs'):
        resulting_data['configs'] = testrail_client.get_configs(project_id)

    with progress_recorder.progress_context('Getting plans'):
        resulting_data['plans'] = [async_to_sync(testrail_client.get_plan)(plan_id) for plan_id in plans_ids]
    with progress_recorder.progress_context('Getting runs'):
        resulting_data['runs_parent_mile'] = [async_to_sync(testrail_client.get_run)(run_id) for run_id in runs_ids]
        resulting_data['runs_parent_plan'] = testrail_client.get_runs_from_plans(resulting_data['plans'])

    with progress_recorder.progress_context('Getting suites'):
        found_suite_ids = []
        for key in ['runs_parent_plan', 'runs_parent_mile']:
            for elem in resulting_data[key]:
                found_suite_ids.append(elem['suite_id'])
        found_suite_ids = set(found_suite_ids)
        resulting_data['suites'] = []
        for suite in testrail_client.get_suites(project_id):
            if suite['id'] in found_suite_ids:
                resulting_data['suites'].append(suite)

    with progress_recorder.progress_context('Getting cases'):
        resulting_data['cases'] = testrail_client.get_cases(project_id, resulting_data['suites'])
    with progress_recorder.progress_context('Getting sections'):
        resulting_data['sections'] = testrail_client.get_sections(project_id, resulting_data['suites'])

    with progress_recorder.progress_context('Getting tests'):
        resulting_data['tests_parent_plan'] = testrail_client.get_tests_for_runs(resulting_data['runs_parent_plan'])
        resulting_data['tests_parent_mile'] = testrail_client.get_tests_for_runs(resulting_data['runs_parent_mile'])
        found_cases = []

        for key in ['tests_parent_plan', 'tests_parent_mile']:
            for elem in resulting_data[key]:
                found_cases.append(elem['case_id'])
        found_cases = set(found_cases)
        cases = []
        for idx, case in enumerate(resulting_data['cases']):
            if case['id'] in found_cases:
                cases.append(case)
        resulting_data['cases'] = cases

    with progress_recorder.progress_context('Getting results'):
        resulting_data['results_parent_plan'] = testrail_client.get_results_for_tests(
            resulting_data['tests_parent_plan']
        )
        resulting_data['results_parent_mile'] = testrail_client.get_results_for_tests(
            resulting_data['tests_parent_mile']
        )

    if not download_attachments:
        save_results_to_redis(resulting_data, backup_filename)
        return

    with progress_recorder.progress_context('Getting attachments'):
        keys_instance_type = [
            ('cases', InstanceType.CASE),
            ('plans', InstanceType.PLAN),
            ('runs_parent_mile', InstanceType.RUN),
            ('runs_parent_plan', InstanceType.RUN),
            ('tests_parent_mile', InstanceType.TEST),
            ('tests_parent_plan', InstanceType.TEST)
        ]
        resulting_data['attachments'] = {}

        for key, instance_type in keys_instance_type:
            resulting_data['attachments'][key] = testrail_client.get_attachments_for_instances(
                resulting_data[key],
                instance_type
            )
    save_results_to_redis(resulting_data, backup_filename)


@shared_task(bind=True)
def upload_plans_runs_task(self, backup_name, config_dict, service_user_login='admin',
                           testy_attachment_url: str = None, testy_project_id=None, testy_plan_id=None):
    progress_recorder = ProgressRecorderContext(self, total=13, description='Upload started')
    with transaction.atomic():
        logging.info('redis about to start')
        redis_client = redis.StrictRedis(settings.REDIS_HOST, settings.REDIS_PORT)
        logging.info('redis started')
        backup = json.loads(redis_client.get(backup_name))

        custom_fields_multi_select = parse_multi_select_from_tr(backup['custom_result_fields'])
        custom_fields_labels = parse_labels_from_tr_fields(backup['custom_result_fields'])

        creator = TestyCreator(service_user_login, testy_attachment_url)

        mappings = {}
        project = Project.objects.get(pk=testy_project_id)

        with progress_recorder.progress_context('Creating users'):
            mappings['users'] = creator.create_users(backup['users'])

        keys_without_mappings = ['suites', 'configs']
        for key in keys_without_mappings:
            with progress_recorder.progress_context(f'Creating {key}'):
                create_method = getattr(creator, f'create_{key}')
                mappings[key] = create_method(backup[key], project.id)

        with progress_recorder.progress_context('Creating sections'):
            mappings['sections'] = creator.create_sections(backup['sections'], mappings['suites'], testy_project_id)

        with progress_recorder.progress_context('Creating plans'):
            mappings['plans'] = creator.create_plans(
                plans=backup['plans'],
                milestones_mappings=None,
                project_id=testy_project_id,
                skip_root_plans=False,
                force_parent=True,
                force_parent_id=testy_plan_id
            )

        with progress_recorder.progress_context('Creating cases'):
            mappings['cases'] = creator.create_cases(backup['cases'], mappings['suites'], mappings['sections'],
                                                     project.id, config_dict['custom_fields_matcher'])

        with progress_recorder.progress_context('Creating runs with plan as parent'):
            mappings['tests_parent_plan'], mappings['runs_parent_plan'] = creator.create_runs(
                runs=backup['runs_parent_plan'],
                mapping=mappings['plans'],
                config_mappings=mappings['configs'],
                tests=backup['tests_parent_plan'],
                case_mappings=mappings['cases'],
                project_id=project.id,
                upload_root_runs=True,
                parent_type=ParentType.PLAN,
                user_mappings=mappings['users']
            )

        with progress_recorder.progress_context('Creating results with plan as parent'):
            mappings['results_parent_plan'] = creator.create_results(
                backup['results_parent_plan'],
                custom_fields_multi_select,
                custom_fields_labels,
                mappings['tests_parent_plan'],
                mappings['users']
            )

        with progress_recorder.progress_context('Creating runs with mile as parent'):
            mappings['tests_parent_mile'], mappings['runs_parent_mile'] = creator.create_runs(
                runs=backup['runs_parent_mile'],
                mapping=None,
                config_mappings=mappings['configs'],
                tests=backup['tests_parent_mile'],
                case_mappings=mappings['cases'],
                project_id=project.id,
                upload_root_runs=True,
                parent_type=ParentType.FORCE_PARENT,
                user_mappings=mappings['users'],
                force_parent_id=testy_plan_id
            )

        with progress_recorder.progress_context('Creating runs with mile as parent'):
            mappings['results_parent_mile'] = creator.create_results(
                backup['results_parent_mile'],
                custom_fields_multi_select,
                custom_fields_labels,
                mappings['tests_parent_mile'],
                mappings['users'],
            )
        if not backup.get('attachments'):
            return
        mappings['attachments'] = {}
        keys = [
            ('cases', 'case_id', InstanceType.CASE),
            ('plans', 'plan_id', InstanceType.PLAN),
            ('runs_parent_plan', 'run_id', InstanceType.RUN),
            ('runs_parent_mile', 'run_id', InstanceType.RUN),
        ]

        testrail_client = TestRailClient(TestrailConfig(**config_dict))

        for key, parent_key, instance_type in keys:
            with progress_recorder.progress_context(f'Creating attachments for {key}'):
                file_attachments = testrail_client.get_attachments_from_list(backup['attachments'][key], parent_key)
                mappings['attachments'].update(
                    creator.attachment_bulk_create(file_attachments, project, mappings['users'], parent_key,
                                                   mappings[key], instance_type)
                )

        keys = [
            ('parent_plan', 'result_id', InstanceType.TEST),
            ('parent_mile', 'result_id', InstanceType.TEST)
        ]

        for key, parent_key, instance_type in keys:
            with progress_recorder.progress_context(f'Creating attachments for {key}'):
                file_attachments = testrail_client.get_attachments_from_list(
                    backup['attachments'][f'tests_{key}'],
                    parent_key
                )
                mappings['attachments'].update(
                    creator.attachment_bulk_create(file_attachments, project, mappings['users'], parent_key,
                                                   mappings[f'results_{key}'], instance_type)
                )
        mappings['steps'] = get_fake_mapping_for_steps(mappings['cases'])
        mappings_keys = [
            ('cases', TestCase, MigratorService.case_update, ['scenario', 'setup', 'description']),
            ('steps', TestCaseStep, MigratorService.step_update, ['scenario', 'expected']),
            ('results_parent_mile', TestResult, TestResultService().result_update, ['comment']),
            ('results_parent_plan', TestResult, TestResultService().result_update, ['comment']),
        ]

        for mapping_key, model_class, update_method, field_list in mappings_keys:
            with progress_recorder.progress_context(f'Looking for attachments in fields of {mapping_key}'):
                creator.update_testy_attachment_urls_async(
                    mappings[mapping_key],
                    model_class,
                    update_method,
                    field_list,
                    config_dict,
                    mappings['attachments']
                )


def save_results_to_redis(results, backup_filename):
    results_json = json.dumps(results)
    redis_client = redis.StrictRedis(settings.REDIS_HOST, settings.REDIS_PORT)

    logging.debug(f'REDIS CLIENT PING {redis_client.ping()}')

    backup_name = f'{backup_filename}{datetime.now()}'
    TestrailBackup.objects.create(name=backup_name, filepath=backup_name)
    redis_client.set(backup_name, results_json)

    if not redis_client.get(backup_name):
        logging.debug('REDIS CLIENT GOT NOTHING')


def parse_multi_select_from_tr(testrail_custom_fields):
    custom_fields = {}
    tr_multiselect_id = 12  # Multiselect type id in testrail
    for custom_field in testrail_custom_fields:
        if custom_field['type_id'] != tr_multiselect_id:
            continue
        key_to_value = {}
        for config in custom_field['configs']:
            field_contents = config['options']['items'].split('\n')
            for content in field_contents:
                key, value = content.split(', ')
                key_to_value[key] = value
        custom_fields[custom_field['system_name']] = deepcopy(key_to_value)
    return custom_fields


def parse_labels_from_tr_fields(testrail_custom_fields):
    system_name_to_label = {}
    for custom_field in testrail_custom_fields:
        system_name_to_label[custom_field['system_name']] = custom_field['label']
    return system_name_to_label
