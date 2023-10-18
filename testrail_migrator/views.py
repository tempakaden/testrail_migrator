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
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import (
    MigratorMilestoneDownloadForm,
    MigratorMilestoneUploadForm,
    MigratorPlanRunDownloadForm,
    MigratorPlanRunUploadForm,
    MigratorProjectDownloadForm,
    MigratorProjectUploadForm,
    MigratorSuiteDownloadForm,
    MigratorSuiteUploadForm,
    TestrailSettingsForm,
)
from .models import TestrailBackup, TestrailSettings
from .tasks import (
    download_milestone_task,
    download_plans_runs_task,
    download_suites_task,
    download_task,
    upload_plans_runs_task,
    upload_suites_task,
    upload_task,
)

UserModel = get_user_model()


def task_status(request, task_id):
    return render(request, 'task_status.html', {'task_id': task_id})


class TestrailSettingsListView(ListView):
    model = TestrailSettings
    context_object_name = 'configs'
    template_name = 'migrator_configs_list.html'
    queryset = TestrailSettings.objects.all()


class TestrailBackupListView(ListView):
    model = TestrailBackup
    context_object_name = 'backups'
    template_name = 'migrator_backups_list.html'
    queryset = TestrailBackup.objects.all()


class TestrailBackupDeleteView(DeleteView):
    model = TestrailBackup
    template_name = 'migrator_confirm_delete.html'
    success_url = reverse_lazy('plugins:testrail_migrator:backup-list')


class TestrailSettingsCreateView(CreateView):
    model = TestrailSettings
    form_class = TestrailSettingsForm
    template_name = 'migrator_settings_form.html'
    success_url = reverse_lazy('plugins:testrail_migrator:settings-list')


class TestrailSettingsUpdateView(UpdateView):
    model = TestrailSettings
    form_class = TestrailSettingsForm
    template_name = 'migrator_settings_form.html'
    success_url = reverse_lazy('plugins:testrail_migrator:settings-list')


class TestrailSettingsDeleteView(DeleteView):
    model = TestrailSettings
    form_class = TestrailSettingsForm
    template_name = 'migrator_confirm_delete.html'
    success_url = reverse_lazy('plugins:testrail_migrator:settings-list')


def redirect_index(request):
    return redirect(reverse('plugins:testrail_migrator:settings-list'))


def download_suites_view(request):
    form = MigratorSuiteDownloadForm()
    if request.method == 'POST':
        form = MigratorSuiteDownloadForm(request.POST)
        if form.is_valid():
            project_id = form.cleaned_data['project_id']
            testrail_suite_ids = form.cleaned_data['testrail_suite_ids']
            download_attachments = form.cleaned_data['download_attachments']
            backup_filename = form.cleaned_data['backup_filename']
            testrail_login = form.cleaned_data['testrail_login']
            testrail_password = form.cleaned_data['testrail_password']
            testrail_settings = form.cleaned_data['testrail_config']

            config_dict = {
                'login': testrail_login,
                'password': testrail_password,
                'api_url': testrail_settings.testrail_api_url,
                'custom_fields_matcher': testrail_settings.custom_fields_matcher
            }

            task = download_suites_task.delay(project_id, config_dict, download_attachments, backup_filename,
                                              testrail_suite_ids)
            return redirect(reverse('plugins:testrail_migrator:task_status', kwargs={'task_id': task.task_id}))
    return render(
        request, 'migrator_form.html', {
            'form': form,
            'button_label': 'Download suites',
            'page_title': 'Download suites'
        }
    )


def upload_suites_view(request):
    form = MigratorSuiteUploadForm()
    if request.method == 'POST':
        form = MigratorSuiteUploadForm(request.POST)
        if form.is_valid():
            backup_instance = form.cleaned_data.get('testrail_backup')
            testrail_login = form.cleaned_data.get('testrail_login')
            testrail_password = form.cleaned_data.get('testrail_password')
            testrail_settings = form.cleaned_data.get('testrail_config')
            testy_project_id = form.cleaned_data.get('testy_project_id')

            config_dict = {
                'login': testrail_login,
                'password': testrail_password,
                'api_url': testrail_settings.testrail_api_url,
                'custom_fields_matcher': testrail_settings.custom_fields_matcher
            }

            task = upload_suites_task.delay(
                testy_project_id=testy_project_id,
                backup_name=backup_instance.name,
                config_dict=config_dict,
                testy_attachment_url=testrail_settings.testy_attachments_url,
            )
            return redirect(reverse('plugins:testrail_migrator:task_status', kwargs={'task_id': task.task_id}))
    return render(
        request, 'migrator_form.html', {
            'form': form,
            'button_label': 'Upload suites',
            'page_title': 'Upload suites'
        }
    )


def download_milestones_view(request):
    form = MigratorMilestoneDownloadForm()
    if request.method == 'POST':
        form = MigratorMilestoneDownloadForm(request.POST)
        if form.is_valid():
            project_id = form.cleaned_data['project_id']
            milestone_ids = form.cleaned_data['testrail_milestone_ids']
            download_attachments = form.cleaned_data['download_attachments']
            ignore_completed = form.cleaned_data['ignore_completed']
            backup_filename = form.cleaned_data['backup_filename']
            testrail_login = form.cleaned_data['testrail_login']
            testrail_password = form.cleaned_data['testrail_password']
            testrail_settings = form.cleaned_data['testrail_config']

            config_dict = {
                'login': testrail_login,
                'password': testrail_password,
                'api_url': testrail_settings.testrail_api_url,
                'custom_fields_matcher': testrail_settings.custom_fields_matcher
            }

            task = download_milestone_task.delay(project_id,
                                                 milestone_ids,
                                                 config_dict,
                                                 download_attachments,
                                                 ignore_completed,
                                                 backup_filename)
            return redirect(reverse('plugins:testrail_migrator:task_status', kwargs={'task_id': task.task_id}))
    return render(request, 'migrator_form.html', {
        'form': form,
        'button_label': 'Download milestones',
        'page_title': 'Download milestones'
    })


def upload_milestones_view(request):
    form = MigratorMilestoneUploadForm()
    if request.method == 'POST':
        form = MigratorMilestoneUploadForm(request.POST)
        if form.is_valid():
            backup_instance = form.cleaned_data.get('testrail_backup')
            upload_root_runs = form.cleaned_data.get('upload_root_runs')
            testrail_login = form.cleaned_data.get('testrail_login')
            testrail_password = form.cleaned_data.get('testrail_password')
            testrail_settings = form.cleaned_data['testrail_config']
            testy_project_id = form.cleaned_data['testy_project_id']

            config_dict = {
                'login': testrail_login,
                'password': testrail_password,
                'api_url': testrail_settings.testrail_api_url,
                'custom_fields_matcher': testrail_settings.custom_fields_matcher
            }

            task = upload_task.delay(
                backup_name=backup_instance.name,
                config_dict=config_dict,
                testy_project_id=testy_project_id,
                testy_attachment_url=testrail_settings.testy_attachments_url,
                upload_root_runs=upload_root_runs
            )
            return redirect(reverse('plugins:testrail_migrator:task_status', kwargs={'task_id': task.task_id}))
    return render(
        request, 'migrator_form.html', {
            'form': form,
            'button_label': 'Upload milestones',
            'page_title': 'Upload milestones'
        }
    )


def download_project_view(request):
    form = MigratorProjectDownloadForm()
    if request.method == 'POST':
        form = MigratorProjectDownloadForm(request.POST)
        if form.is_valid():
            project_id = form.cleaned_data['project_id']
            download_attachments = form.cleaned_data['download_attachments']
            ignore_completed = form.cleaned_data['ignore_completed']
            backup_filename = form.cleaned_data['backup_filename']
            testrail_login = form.cleaned_data['testrail_login']
            testrail_password = form.cleaned_data['testrail_password']
            testrail_settings = form.cleaned_data['testrail_config']

            config_dict = {
                'login': testrail_login,
                'password': testrail_password,
                'api_url': testrail_settings.testrail_api_url,
                'custom_fields_matcher': testrail_settings.custom_fields_matcher
            }

            task = download_task.delay(project_id, config_dict, download_attachments, ignore_completed,
                                       backup_filename)
            return redirect(reverse('plugins:testrail_migrator:task_status', kwargs={'task_id': task.task_id}))

    return render(
        request, 'migrator_form.html', {
            'form': form,
            'button_label': 'Download project',
            'page_title': 'Download project'
        }
    )


def upload_project_view(request):
    form = MigratorProjectUploadForm()
    if request.method == 'POST':
        form = MigratorProjectUploadForm(request.POST)
        if form.is_valid():
            backup_instance = form.cleaned_data.get('testrail_backup')
            upload_root_runs = form.cleaned_data.get('upload_root_runs')
            testrail_login = form.cleaned_data.get('testrail_login')
            testrail_password = form.cleaned_data.get('testrail_password')
            testrail_settings = form.cleaned_data['testrail_config']

            config_dict = {
                'login': testrail_login,
                'password': testrail_password,
                'api_url': testrail_settings.testrail_api_url,
                'custom_fields_matcher': testrail_settings.custom_fields_matcher
            }

            task = upload_task.delay(
                backup_name=backup_instance.name,
                config_dict=config_dict,
                testy_attachment_url=testrail_settings.testy_attachments_url,
                upload_root_runs=upload_root_runs
            )
            return redirect(reverse('plugins:testrail_migrator:task_status', kwargs={'task_id': task.task_id}))
    return render(
        request, 'migrator_form.html', {
            'form': form,
            'button_label': 'Upload project',
            'page_title': 'Upload project'
        }
    )


def download_plans_runs_view(request):
    form = MigratorPlanRunDownloadForm()
    if request.method == 'POST':
        form = MigratorPlanRunDownloadForm(request.POST)
        if form.is_valid():
            project_id = form.cleaned_data['project_id']
            plan_ids = form.cleaned_data['testrail_plan_ids']
            run_ids = form.cleaned_data['testrail_run_ids']
            download_attachments = form.cleaned_data['download_attachments']
            backup_filename = form.cleaned_data['backup_filename']
            testrail_login = form.cleaned_data['testrail_login']
            testrail_password = form.cleaned_data['testrail_password']
            testrail_settings = form.cleaned_data['testrail_config']

            config_dict = {
                'login': testrail_login,
                'password': testrail_password,
                'api_url': testrail_settings.testrail_api_url,
                'custom_fields_matcher': testrail_settings.custom_fields_matcher
            }

            task = download_plans_runs_task.delay(
                project_id,
                config_dict,
                download_attachments,
                backup_filename,
                plan_ids,
                run_ids
            )
            return redirect(reverse('plugins:testrail_migrator:task_status', kwargs={'task_id': task.task_id}))
    return render(request, 'migrator_form.html', {
        'form': form,
        'button_label': 'Download plans/runs',
        'page_title': 'Download plans/runs'
    })


def upload_plans_runs_view(request):
    form = MigratorPlanRunUploadForm()
    if request.method == 'POST':
        form = MigratorPlanRunUploadForm(request.POST)
        if form.is_valid():
            backup_instance = form.cleaned_data.get('testrail_backup')
            testrail_login = form.cleaned_data.get('testrail_login')
            testrail_password = form.cleaned_data.get('testrail_password')
            testrail_settings = form.cleaned_data['testrail_config']
            testy_project_id = form.cleaned_data['testy_project_id']
            testy_plan_id = form.cleaned_data['testy_plan_id']

            config_dict = {
                'login': testrail_login,
                'password': testrail_password,
                'api_url': testrail_settings.testrail_api_url,
                'custom_fields_matcher': testrail_settings.custom_fields_matcher
            }

            task = upload_plans_runs_task.delay(
                backup_name=backup_instance.name,
                config_dict=config_dict,
                testy_project_id=testy_project_id,
                testy_plan_id=testy_plan_id,
                testy_attachment_url=testrail_settings.testy_attachments_url,
            )

            return redirect(reverse('plugins:testrail_migrator:task_status', kwargs={'task_id': task.task_id}))
    return render(
        request, 'migrator_form.html', {
            'form': form,
            'button_label': 'Upload milestones',
            'page_title': 'Upload milestones'
        }
    )
