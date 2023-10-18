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
from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views

urlpatterns = [
    path('', views.redirect_index, name='migrator-index'),

    path('download/project/', login_required(views.download_project_view), name='download-project'),
    path('download/milestones/', login_required(views.download_milestones_view), name='download-milestones'),
    path('download/suites/', login_required(views.download_suites_view), name='download-suites'),
    path('download/plans/', login_required(views.download_plans_runs_view), name='download-plans'),
    path('upload/project/', login_required(views.upload_project_view), name='upload-project'),
    path('upload/milestones/', login_required(views.upload_milestones_view), name='upload-milestones'),
    path('upload/suites/', login_required(views.upload_suites_view), name='upload-suites'),
    path('upload/plans/', login_required(views.upload_plans_runs_view), name='upload-plans'),

    path('configs/', login_required(views.TestrailSettingsListView.as_view()), name='settings-list'),
    path('configs/add/', login_required(views.TestrailSettingsCreateView.as_view()), name='settings-add'),
    path('configs/edit/<int:pk>/', login_required(views.TestrailSettingsUpdateView.as_view()), name='settings-edit'),
    path(
        'configs/delete/<int:pk>/',
        login_required(views.TestrailSettingsDeleteView.as_view()),
        name='settings-delete'
    ),

    path('backups/', login_required(views.TestrailBackupListView.as_view()), name='backup-list'),
    path('backups/delete/<int:pk>/', login_required(views.TestrailBackupDeleteView.as_view()), name='backup-delete'),

    path('task_status/<str:task_id>/', views.task_status, name='task_status')
]
