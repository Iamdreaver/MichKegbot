#!/usr/bin/env python
#
# Copyright 2012 Mike Wakerly <opensource@hoho.com>
#
# This file is part of the Pykeg package of the Kegbot project.
# For more information on Pykeg or Kegbot, see http://kegbot.org/
#
# Pykeg is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# Pykeg is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Pykeg.  If not, see <http://www.gnu.org/licenses/>.

from django.contrib import messages
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from socialregistration.clients.oauth import OAuthError
from socialregistration.contrib.twitter.client import Twitter
from django.contrib.admin.views.decorators import staff_member_required

from . import models

class TwitterClient(Twitter):
  def set_callback_url(self, url):
    self.callback_url = url
  def get_callback_url(self):
    return self.callback_url

def _base_url(request):
  """Returns the base absolute URL for this request."""
  host = request.META['HTTP_HOST']
  return 'http://' + host

def _site_url(request, url_name):
  """Shortcut for getting the kbsite-prfixed named URL."""
  kwargs = {
    'kbsite_name': request.kbsite.url(),
  }
  return _base_url(request) + reverse(url_name, kwargs=kwargs)

def _site_twitter_session_key(request):
  """Returns a site-specific session key."""
  return 'site_twitter_%s' % (request.kbsite.id,)

@staff_member_required
def site_twitter_redirect(request):
  if request.POST.get('remove') is not None:
    request.kbsite.twitter_profile.delete()
    url = _site_url(request, 'kegadmin-connections')
    messages.success(request, 'Removed Twitter account.')
    return HttpResponseRedirect(url)

  client = TwitterClient()
  url = _site_url(request, 'site_twitter_callback')
  client.set_callback_url(url)
  request.session[_site_twitter_session_key(request)] = client

  try:
    return HttpResponseRedirect(client.get_redirect_url())
  except OAuthError, error:
    url = _site_url(request, 'kegadmin-connections')
    messages.error(request, 'Error: %s' % str(error))
    return HttpResponseRedirect(url)

@staff_member_required
def site_twitter_callback(request):
  token = None
  try:
    client = request.session[_site_twitter_session_key(request)]
    token = client.complete(dict(request.GET.items()))
  except KeyError:
    messages.error(request, 'Session expired.')
  except OAuthError, error:
    messages.error(request, str(error))
  else:
    site = request.kbsite
    user_info = client.get_user_info()

    try:
      profile = models.SiteTwitterProfile.objects.get(site=site)
    except models.SiteTwitterProfile.DoesNotExist:
      profile = models.SiteTwitterProfile(site=site)
    profile.oauth_token = token.key
    profile.oauth_token_secret = token.secret
    profile.twitter_name = user_info['screen_name']
    profile.twitter_id = int(user_info['user_id'])
    profile.enabled = True
    profile.save()
    messages.success(request, 'Successfully linked to @%s' % user_info['screen_name'])

  url = _site_url(request, 'kegadmin-connections')
  return HttpResponseRedirect(url)
