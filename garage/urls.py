from django.urls import path
from . import app_views, category_views, export_views, lifespan_views, parts_views, snooze_views, review_views, statistics_views, maintenance_views, history_views, photo_views, strava_views, usage_views, views

app_name = 'garage'
urlpatterns = [
    path('', views.index, name='index'),
    path('manifest.webmanifest', app_views.manifest, name='manifest'),
    path('sw.js', app_views.service_worker, name='service-worker'),
    path('offline/', app_views.offline, name='offline'),
    path('more/', app_views.more, name='more'),
    path('add/', app_views.add, name='add'),
    path('rides/<uuid:pk>/review/', review_views.ride_review, name='ride-review'),
    path('rides/<uuid:pk>/review/preview/', review_views.ride_review_preview, name='ride-review-preview'),
]
for kind, plural in [('bike', 'bikes'), ('item', 'items'), ('category', 'categories')]:
    urlpatterns += [
        path(plural + '/', views.inventory_list, {'kind': kind}, name=kind + '-list'),
        path(plural + '/new/', views.inventory_edit, {'kind': kind}, name=kind + '-create'),
        path(plural + '/<uuid:pk>/', views.inventory_detail, {'kind': kind}, name=kind + '-detail'),
        path(plural + '/<uuid:pk>/edit/', views.inventory_edit, {'kind': kind}, name=kind + '-edit'),
    ]
    if kind != 'category':
        urlpatterns += [
            path(plural + '/<uuid:pk>/retire/', views.retire, {'kind': kind}, name=kind + '-retire'),
            path(plural + '/<uuid:pk>/reactivate/', views.reactivate, {'kind': kind}, name=kind + '-reactivate'),
        ]
urlpatterns += [
    path('categories/starter/', category_views.starter, name='category-starter'),
    path('items/used/new/', views.inventory_edit, {'kind': 'item', 'used': True}, name='item-used-create'),
    path('items/<uuid:item_pk>/mount/', views.installation_edit, name='installation-create'),
    path('installations/<uuid:pk>/edit/', views.installation_edit, name='installation-edit'),
    path('items/<uuid:item_pk>/readings/new/', views.baseline_edit, name='baseline-create'),
    path('items/<uuid:pk>/lifespan/', lifespan_views.lifespan_edit, name='item-lifespan'),
    path('items/<uuid:pk>/parts/new/', parts_views.part_create, name='item-part-create'),
    path('readings/<uuid:pk>/edit/', views.baseline_edit, name='baseline-edit'),
]
for action in ['close', 'replace', 'transfer']:
    urlpatterns.append(path('installations/<uuid:pk>/' + action + '/', views.installation_action,
                            {'action': action}, name='installation-' + action))

urlpatterns += [
    path('usage/profiles/', usage_views.profile_list, name='usage-profile-list'),
    path('usage/profiles/new/', usage_views.profile_edit, name='usage-profile-create'),
    path('usage/profiles/<uuid:pk>/', usage_views.profile_detail, name='usage-profile-detail'),
    path('usage/profiles/<uuid:pk>/revise/', usage_views.profile_edit, name='usage-profile-revise'),
    path('usage/profiles/<uuid:pk>/history/', usage_views.profile_edit, {'correction': True}, name='usage-profile-history'),
    path('usage/rides/', usage_views.ride_list, name='usage-ride-list'),
    path('usage/rides/<uuid:pk>/', usage_views.ride_detail, name='usage-ride-detail'),
    path('usage/overrides/<uuid:pk>/delete/', usage_views.override_delete, name='usage-override-delete'),
]

urlpatterns += [
    path('history/', history_views.history, name='history'),
    path('history/fit/preview/', history_views.fit_preview, name='history-preview'),
    path('history/fit/execute/', history_views.fit_execute, name='history-execute'),
    path('history/runs/<uuid:pk>/', history_views.import_run, name='history-run'),
    path('history/runs/<uuid:pk>/cancel/', history_views.import_cancel, name='history-cancel'),
    path('history/bikes/', history_views.bike_batch, name='history-bike-batch'),
    path('history/manual/new/', history_views.manual_ride, name='history-manual-create'),
    path('history/manual/<uuid:pk>/edit/', history_views.manual_ride, name='history-manual-edit'),
    path('history/sources/<uuid:pk>/withdraw/', history_views.source_withdraw, name='history-source-withdraw'),
    path('history/sources/<uuid:pk>/separate/', strava_views.source_separate, name='history-source-separate'),
    path('history/sources/<uuid:pk>/merge/', strava_views.source_merge, name='history-source-merge'),
    path('history/sources/<uuid:pk>/keep/', strava_views.source_keep, name='history-source-keep'),
]

urlpatterns += [
    path('strava/', strava_views.strava_page, name='strava'),
    path('strava/sync/', strava_views.strava_sync, name='strava-sync'),
    path('strava/sync-all/', strava_views.sync_all, name='strava-sync-all'),
    path('strava/import/', strava_views.strava_import, name='strava-import'),
    path('strava/gear/<uuid:pk>/', strava_views.gear_link, name='strava-gear'),
    path('strava/remove/', strava_views.strava_remove, name='strava-remove'),
]

for kind, plural in [("bike", "bikes"), ("item", "items")]:
    urlpatterns.append(path(plural + '/<uuid:target_pk>/photos/new/', photo_views.photo_upload,
                            {"kind": kind}, name=kind + '-photo-create'))
urlpatterns += [
    path('photos/<uuid:pk>/content/', photo_views.photo_content, name='photo-content'),
    path('photos/<uuid:pk>/replace/', photo_views.photo_upload, name='photo-replace'),
    path('photos/<uuid:pk>/delete/', photo_views.photo_delete, name='photo-delete'),
]

urlpatterns += [
    path('maintenance/', maintenance_views.maintenance_list, name='maintenance'),
    path('maintenance/events/<uuid:pk>/', maintenance_views.event_detail, name='service-event-detail'),
    path('maintenance/maintenance-rule/<uuid:pk>/snooze/', snooze_views.snooze_edit, name='maintenance-rule-snooze'),
    path('maintenance/events/<uuid:target_pk>/photos/new/', photo_views.photo_upload, {"kind": "service-event"}, name='service-event-photo-create'),
]
for kind in maintenance_views.KINDS:
    urlpatterns += [
        path('maintenance/' + kind + '/new/', maintenance_views.maintenance_edit, {'kind': kind}, name=kind + '-create'),
        path('maintenance/' + kind + '/<uuid:pk>/edit/', maintenance_views.maintenance_edit, {'kind': kind}, name=kind + '-edit'),
        path('maintenance/' + kind + '/<uuid:pk>/delete/', maintenance_views.maintenance_delete, {'kind': kind}, name=kind + '-delete'),
    ]

urlpatterns += [path("statistics/", statistics_views.statistics_page, name="statistics")]

urlpatterns += [
    path('export/', export_views.export_page, name='export'),
    path('export/json/', export_views.download, {'kind': 'json'}, name='export-json'),
    path('export/csv/', export_views.download, {'kind': 'csv'}, name='export-csv'),
]
