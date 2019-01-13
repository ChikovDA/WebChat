from django.http import HttpResponse
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render
from django.views.generic import TemplateView
from django.views.generic.edit import FormView
from django.contrib.auth.forms import UserCreationForm


def index(request):
 total_users = User.objects.all().count()

 return render(request,'index.html',context={'total_users':total_users},)


class MainView(TemplateView):
    template_name = 'index.html'

    def get(self, request):
        if request.user.is_authenticated:
            total_users = User.objects.all().count()
            context = {'total_users':total_users}
            return render(request, self.template_name, context,)
        else:
            return render(request, self.template_name, {})


class RegisterFormView(FormView):

    form_class = UserCreationForm
    success_url = '/accounts/login/?next=/'

    template_name = 'registration/addUser.html'

    def form_valid(self, form):
        form.save()
        return super(RegisterFormView, self).form_valid(form)

    def form_invalid(self, form):
        return super(RegisterFormView, self).form_invalid(form)
