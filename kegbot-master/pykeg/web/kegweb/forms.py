from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm

from registration.models import RegistrationProfile
from registration.forms import RegistrationForm

from pykeg.core import models

class LoginForm(AuthenticationForm):
  next_page = forms.CharField(required=False, widget=forms.HiddenInput)

class KegbotRegistrationForm(RegistrationForm):
  WEIGHT_CHOICES = (
      (100, 'less than 100'),
      (120, '100-130'),
      (150, '131-170'),
      (180, '171+'),
  )
  GENDER_CHOICES = (
      ('male', 'Male'),
      ('female', 'Female'),
  )
  gender = forms.ChoiceField(choices=GENDER_CHOICES,
      help_text='Used for BAC estimation.')
  weight = forms.ChoiceField(choices=WEIGHT_CHOICES,
      help_text='Used for BAC estimation, kept private. You can lie.')

  def save(self, profile_callback=None):
    new_user = RegistrationProfile.objects.create_inactive_user(username=self.cleaned_data['username'],
                                                                password=self.cleaned_data['password1'],
                                                                email=self.cleaned_data['email'],
                                                                send_email=False,
                                                                profile_callback=profile_callback)
    new_user.is_active = True
    new_user.save()
    new_profile, is_new = models.UserProfile.objects.get_or_create(user=new_user)
    new_profile.gender = self.cleaned_data['gender']
    new_profile.weight = self.cleaned_data['weight']
    new_profile.save()
    return new_user


class UserProfileForm(forms.ModelForm):
  class Meta:
    model = models.UserProfile
    fields = ('gender', 'weight')


class MugshotForm(forms.Form):
  new_mugshot = forms.ImageField(required=True)


UNASSIGNED_TOKEN_QS = models.AuthenticationToken.objects.filter(user=None)
NEW_USERS = models.User.objects.all().order_by('-date_joined')

class ClaimTokenForm(forms.Form):
  token = forms.ModelChoiceField(queryset=UNASSIGNED_TOKEN_QS)
  user = forms.ModelChoiceField(queryset=NEW_USERS)

class RegenerateApiKeyForm(forms.Form):
  pass

