from django.conf.urls import patterns, include, url

from . import views

app_name = 'publicroom'

urlpatterns = [
    url(r'^$', views.index, name='index'),
    url(r'^registration/', views.RegisterFormView.as_view(), name='registration'),

]
