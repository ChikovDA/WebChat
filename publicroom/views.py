from django.http import HttpResponse
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render


def index(request):
 total_users = User.objects.all().count()

 return render(request,'index.html',context={'total_users':total_users},)

