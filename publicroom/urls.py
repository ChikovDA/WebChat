from django.conf.urls import patterns, include, url

from . import views

app_name = 'publicroom'

urlpatterns = [
    url(r'^$', views.index, name='index'),


]
