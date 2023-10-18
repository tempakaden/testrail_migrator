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
from datetime import datetime
from typing import Any, Dict

from core.api.v1.serializers import ProjectSerializer
from core.models import Project
from core.services.attachments import AttachmentService
from core.services.projects import ProjectService
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from tests_description.models import TestCase, TestCaseStep, TestSuite
from tests_description.selectors.cases import TestCaseSelector
from tests_description.services.cases import TestCaseService
from tests_description.services.suites import TestSuiteService
from tests_representation.models import Parameter, Test, TestPlan, TestResult, TestStepResult
from tests_representation.services.parameters import ParameterService
from tests_representation.services.results import TestResultService
from tests_representation.services.testplans import TestPlanService
from tests_representation.services.tests import TestService

UserModel = get_user_model()


class MigratorService:
    @staticmethod
    def suite_create(data) -> TestSuite:
        non_side_effect_fields = TestSuiteService.non_side_effect_fields
        suite = TestSuite.model_create(
            fields=non_side_effect_fields,
            data=data,
        )
        return suite

    @staticmethod
    def step_update(step, data) -> TestCaseStep:
        non_side_effect_fields = TestCaseService.non_side_effect_fields
        step, _ = step.model_update(
            fields=non_side_effect_fields,
            data=data,
        )
        return step

    @staticmethod
    def suites_bulk_create(data_list):
        suites = []
        non_side_effect_fields = TestSuiteService.non_side_effect_fields
        for data in data_list:
            test_suite = TestSuite.model_create(non_side_effect_fields, data=data, commit=False)
            test_suite.lft = 0
            test_suite.rght = 0
            test_suite.tree_id = 0
            test_suite.level = 0
            suites.append(test_suite)
        TestSuite.objects.rebuild()
        return TestSuite.objects.bulk_create(suites)

    def step_create(self, data: Dict[str, Any]) -> TestCaseStep:
        data['name'] = data['name'][:254] if len(data['name']) > 255 else data['name']
        step: TestCaseStep = TestCaseStep.model_create(
            fields=TestCaseService.step_non_side_effect_fields,
            data=data
        )

        for attachment in data.get('attachments', []):
            AttachmentService().attachment_set_content_object(attachment, step)

        return step

    @transaction.atomic
    def case_with_steps_create(self, data: Dict[str, Any]) -> TestCase:
        case = self.case_create(data)

        for step in data.pop('steps', []):
            step['test_case'] = case
            step['project'] = case.project
            step['test_case_history_id'] = case.history.first().history_id
            self.step_create(step)
        return case

    def case_create(self, data: Dict[str, Any]) -> TestCase:

        case: TestCase = TestCase.model_create(
            fields=TestCaseService.case_non_side_effect_fields,
            data=data,
            commit=False
        )
        case.updated_at = timezone.make_aware(datetime.fromtimestamp(data['updated_at']), timezone.utc)
        case.created_at = timezone.make_aware(datetime.fromtimestamp(data['created_at']), timezone.utc)
        case.save()
        for attachment in data.get('attachments', []):
            AttachmentService().attachment_set_content_object(attachment, case)
        return case

    @staticmethod
    def case_update(case: TestCase, data) -> TestCase:
        non_side_effect_fields = TestCaseService.case_non_side_effect_fields
        case, _ = case.model_update(
            fields=non_side_effect_fields,
            data=data,
        )
        return case

    @staticmethod
    def parameter_bulk_create(data_list):
        non_side_effect_fields = ParameterService.non_side_effect_fields
        parameters = [Parameter.model_create(fields=non_side_effect_fields, data=data, commit=False) for data in
                      data_list]
        return Parameter.objects.bulk_create(parameters)

    def testplan_bulk_create_with_tests(self, data_list):
        test_plans = []
        for data in data_list:
            parameters = data.get('parameters', [])
            test_plans.append(
                self.make_testplan_model(
                    data,
                    parameters=[Parameter.objects.get(pk=parameter) for parameter in parameters]
                )
            )
        TestPlan.objects.rebuild()
        created_tests = []
        for test_plan, data in zip(test_plans, data_list):
            if data.get('test_cases'):
                created_tests.extend(TestService().bulk_test_create([test_plan], data['test_cases']))
        return created_tests, test_plans

    @staticmethod
    @transaction.atomic
    def result_create(data: Dict[str, Any], user) -> TestResult:
        test_result: TestResult = TestResult.model_create(
            fields=TestResultService.non_side_effect_fields,
            data=data,
            commit=False,
        )
        test_result.user = user
        test_result.project = test_result.test.case.project
        test_result.test_case_version = TestCaseSelector().case_version(test_result.test.case)
        test_result.full_clean()
        test_result.updated_at = data['updated_at']
        test_result.created_at = data['created_at']
        test_result.save()

        for attachment in data.get('attachments', []):
            AttachmentService().attachment_set_content_object(attachment, test_result)

        for steps_results in data.get('steps_results', []):
            steps_results['test_result'] = test_result
            steps_results['project'] = test_result.project
            TestStepResult.model_create(
                fields=TestResultService.step_non_side_effect_fields,
                data=steps_results
            )

        return test_result

    def testplan_bulk_create(self, validated_data):
        test_plans = []
        for data in validated_data:
            test_plans.append(self.make_testplan_model(data))
        TestPlan.objects.rebuild()

        return test_plans

    @staticmethod
    def create_project(project) -> Project:
        data = {
            'name': project['name'],
            'description': project['announcement'] if project['announcement'] else ''
        }
        serializer = ProjectSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return ProjectService().project_create(serializer.validated_data)

    @staticmethod
    def tests_bulk_create_by_data_list(data_list):
        non_side_effect_fields = TestService.non_side_effect_fields
        test_objects = [Test.model_create(fields=non_side_effect_fields, data=data, commit=False) for data in
                        data_list]
        return Test.objects.bulk_create(test_objects)

    @staticmethod
    def user_create(data) -> UserModel:
        user, _ = UserModel.objects.get_or_create(
            username__iexact=data['username'],
            defaults=data
        )

        return user

    @staticmethod
    def make_testplan_model(data, parameters=None):
        testplan = TestPlan.model_create(
            fields=TestPlanService.non_side_effect_fields,
            data=data,
            commit=False
        )
        testplan.lft = 0
        testplan.rght = 0
        testplan.tree_id = 0
        testplan.level = 0

        testplan.save()
        if parameters:
            testplan.parameters.set(parameters)

        return testplan
