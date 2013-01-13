from django.conf import settings

from pykeg.core import features
from pykeg.core import models
from pykeg.web.kegweb.forms import LoginForm

def enabled_features(request):
  """Adds a USE_FEATURENAME flags for each enabled feature (see features.py)"""
  # TODO(mikey): this might make it harder to diagnose why features aren't
  # visible/being used.
  ret = {}
  ret['USE_FACEBOOK'] = features.use_facebook()
  ret['USE_TWITTER'] = features.use_twitter()
  return ret

def kbsite(request):
  kbsite = getattr(request, 'kbsite', None)
  analytics_id = None
  if kbsite:
    analytics_id = kbsite.settings.google_analytics_id

  guest_info = {
    'name': 'guest',
    'image': None,
  }
  if kbsite:
    guest_info['name'] = kbsite.settings.guest_name
    guest_info['image'] = kbsite.settings.guest_image

  ret = {
    'DEBUG': settings.DEBUG,
    'kbsite': getattr(request, 'kbsite', None),
    'request_path': request.path,
    'login_form': LoginForm(initial={'next_page': request.path}),
    'GOOGLE_ANALYTICS_ID': analytics_id,
    'guest_info': guest_info,
  }
  return ret
