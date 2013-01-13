# -*- coding: latin-1 -*-
# Copyright 2010 Mike Wakerly <opensource@hoho.com>
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

import datetime
import os
import random

from django.conf import settings
from django.core.urlresolvers import reverse
from django.db import models
from django.db.models.signals import post_save
from django.db.models.signals import pre_save
from django.contrib.sites.models import Site
from django.contrib.auth.models import User

from autoslug import AutoSlugField

from pykeg.core import kb_common
from pykeg.core import fields
from pykeg.core import imagespecs
from pykeg.core import managers
from pykeg.core import stats

from kegbot.util import units
from kegbot.util import util

from kegbot.api import models_pb2
from kegbot.api import protoutil

from pykeg.web.api.apikey import ApiKey

from pykeg.beerdb import models as bdb

"""Django models definition for the kegbot database."""

def _set_seqn_pre_save(sender, instance, **kwargs):
  if instance.seqn:
    return
  prev = sender.objects.filter(site=instance.site).order_by('-seqn')
  if not prev.count():
    seqn = 1
  else:
    seqn = prev[0].seqn + 1
  instance.seqn = seqn

class KegbotSite(models.Model):
  name = models.CharField(max_length=64, unique=True,
      help_text='A short single-word name for this site, eg "default" or "sfo"')
  is_active = models.BooleanField(default=True,
      help_text='On/off switch for this site.')
  is_setup = models.BooleanField(default=True,
      help_text='True if the site has completed setup.',
      editable=False)

  def __str__(self):
    return self.name

  def url(self):
    if self.name == 'default':
      return ''
    return self.name

  def full_url(self):
    domain = Site.objects.get_current().domain
    parts = ['http://%s' % domain]
    if self.url():
      parts.append(self.url())
    return '/'.join(parts)

  def GetStatsRecord(self):
    try:
      return SystemStats.objects.get(site=self)
    except SystemStats.DoesNotExist:
      return None

  def GetStats(self):
    record = self.GetStatsRecord()
    if record:
      return record.stats
    return {}

def _kegbotsite_post_save(sender, instance, **kwargs):
  """Creates a SiteSettings object if none already exists."""
  settings, _ = SiteSettings.objects.get_or_create(site=instance)
post_save.connect(_kegbotsite_post_save, sender=KegbotSite)

PRIVACY_CHOICES = (
  ('public', 'Public: Browsing does not require login'),
  ('members', 'Members only: Must log in to browse'),
  ('staff', 'Staff only: Only logged-in staff accounts may browse'),
)

DEFAULT_PRIVACY = 'public'

class SiteSettings(models.Model):
  DISPLAY_UNITS_CHOICES = (
    ('metric', 'Metric (mL, L)'),
    ('imperial', 'Imperial (oz, pint)'),
  )

  site = models.OneToOneField(KegbotSite, related_name='settings')
  display_units = models.CharField(max_length=64, choices=DISPLAY_UNITS_CHOICES,
      default='imperial',
      help_text='Default unit system to use when displaying volumetric data.')
  title = models.CharField(max_length=64, blank=True, null=True,
      help_text='The title of this site. Example: "Kegbot San Francisco"')
  description = models.TextField(blank=True, null=True,
      help_text='Description of this site')
  background_image = models.ForeignKey('Picture', blank=True, null=True,
      help_text='Background for this site.')
  event_web_hook = models.URLField(blank=True, null=True, verify_exists=False,
      help_text='Web hook URL for newly-generated events.')
  google_analytics_id = models.CharField(blank=True, null=True, max_length=64,
      help_text='Set to your Google Analytics ID to enable tracking. '
      'Example: UA-XXXX-y')
  session_timeout_minutes = models.PositiveIntegerField(
      default=kb_common.DRINK_SESSION_TIME_MINUTES,
      help_text='Maximum time in minutes that a session may be idle (no pours) '
          'before it is considered to be finished.  '
          'Recommended value is %s.' % kb_common.DRINK_SESSION_TIME_MINUTES)
  privacy = models.CharField(max_length=63, choices=PRIVACY_CHOICES,
      default=DEFAULT_PRIVACY,
      help_text='Whole-system setting for system privacy.')
  guest_name = models.CharField(max_length=63, default='guest',
      help_text='Name to be shown in various places for unauthenticated pours.')
  guest_image = models.ForeignKey('Picture', blank=True, null=True,
      related_name='guest_images',
      help_text='Profile picture to be shown for unauthenticated pours.')
  default_user = models.ForeignKey(User, blank=True, null=True,
      help_text='Default user to set as owner for unauthenticated drinks. '
          'When set, the "guest" user will not be used. This is mostly '
          'useful for closed / single user systems.')
  registration_allowed = models.BooleanField(default=True,
      help_text='Whether to allow new user registration.')
  registration_confirmation = models.BooleanField(default=False,
      help_text='Whether registration requires e-mail confirmation.')

  class Meta:
    verbose_name_plural = "site settings"

  def GetSessionTimeoutDelta(self):
    return datetime.timedelta(minutes=self.session_timeout_minutes)

class UserProfile(models.Model):
  """Extra per-User information."""
  GENDER_CHOICES = (
    ('male', 'male'),
    ('female', 'female'),
  )
  def __str__(self):
    return "profile for %s" % (self.user,)

  def FacebookProfile(self):
    if 'socialregistration' not in settings.INSTALLED_APPS:
      return None
    qs = self.user.facebookprofile_set.all()
    if qs:
      return qs[0]

  def TwitterProfile(self):
    if 'socialregistration' not in settings.INSTALLED_APPS:
      return None
    qs = self.user.twitterprofile_set.all()
    if qs:
      return qs[0]

  def GetStatsRecord(self):
    try:
      return UserStats.objects.get(user=self)
    except UserStats.DoesNotExist:
      return None

  def GetStats(self):
    record = self.GetStatsRecord()
    if record:
      return record.stats
    return {}

  def RecomputeStats(self):
    self.user.stats.all().delete()
    last_d = self.user.drinks.valid().order_by('-time')
    if last_d:
      last_d[0]._UpdateUserStats()

  def GetApiKey(self):
    return ApiKey(self.user.id, self.api_secret)

  @models.permalink
  def get_absolute_url(self):
    return ('kb-drinker', ('', self.user.username))

  user = models.OneToOneField(User)
  gender = models.CharField(max_length=8, choices=GENDER_CHOICES)
  weight = models.FloatField()
  mugshot = models.ForeignKey('Picture', blank=True, null=True)
  api_secret = models.CharField(max_length=256, blank=True, null=True,
      default=ApiKey.NewSecret)

def _user_profile_pre_save(sender, instance, **kwargs):
  if not instance.api_secret:
    instance.api_secret = ApiKey.NewSecret()
  # TODO(mikey): validate secret (length, hex chars) here too.
pre_save.connect(_user_profile_pre_save, sender=UserProfile)

def _user_post_save(sender, instance, **kwargs):
  defaults = {
    'weight': kb_common.DEFAULT_NEW_USER_WEIGHT,
    'gender': kb_common.DEFAULT_NEW_USER_GENDER,
  }
  profile, new = UserProfile.objects.get_or_create(user=instance,
      defaults=defaults)
post_save.connect(_user_post_save, sender=User)


class KegSize(models.Model):
  """ A convenient table of common Keg sizes """
  def __str__(self):
    gallons = units.Quantity(self.volume_ml).InUSGallons()
    return "%s [%.2f gal]" % (self.name, gallons)

  name = models.CharField(max_length=128)
  volume_ml = models.FloatField()


class KegTap(models.Model):
  """A physical tap of beer."""
  site = models.ForeignKey(KegbotSite, related_name='taps')
  seqn = models.PositiveIntegerField(editable=False)
  name = models.CharField(max_length=128,
      help_text='The display name for this tap. Example: Main Tap.')
  meter_name = models.CharField(max_length=128,
      help_text='The name of the flow meter reporting to this tap. '
      'Example: kegboard.flow0')
  relay_name = models.CharField(max_length=128, blank=True, null=True,
      help_text='If a relay is attached to this tap, give its '
      'name here. Example: kegboard.relay0')
  ml_per_tick = models.FloatField(default=(1000.0/2200.0))
  description = models.TextField(blank=True, null=True)
  current_keg = models.OneToOneField('Keg', blank=True, null=True,
      related_name='current_tap')
  max_tick_delta = models.PositiveIntegerField(default=100)
  temperature_sensor = models.ForeignKey('ThermoSensor', blank=True, null=True)

  def __str__(self):
    return "%s: %s" % (self.meter_name, self.name)

  def Temperature(self):
    if self.temperature_sensor:
      last_rec = self.temperature_sensor.thermolog_set.all().order_by('-time')
      if last_rec:
        return last_rec[0]
    return None

pre_save.connect(_set_seqn_pre_save, sender=KegTap)

class Keg(models.Model):
  """ Record for each installed Keg. """
  class Meta:
    unique_together = ('site', 'seqn')

  @models.permalink
  def get_absolute_url(self):
    return ('kb-keg', (self.site.url(), str(self.seqn)))

  def full_volume(self):
    return self.size.volume_ml

  def served_volume(self):
    drinks = Drink.objects.filter(keg__exact=self, status__exact='valid')
    total = 0
    for d in drinks:
      total += d.volume_ml
    return total

  def spilled_volume(self):
    return self.spilled_ml

  def remaining_volume(self):
    return self.full_volume() - self.served_volume() - self.spilled_volume()

  def percent_full(self):
    result = float(self.remaining_volume()) / float(self.full_volume()) * 100
    result = max(min(result, 100), 0)
    return result

  def keg_age(self):
    if self.status == 'online':
      end = datetime.datetime.now()
    else:
      end = self.end_time
    return end - self.start_time

  def is_empty(self):
    return float(self.remaining_volume()) <= 0

  def is_active(self):
    return self.status == 'online'

  def previous(self):
    q = Keg.objects.filter(site=self.site, start_time__lt=self.start_time).order_by('-start_time')
    if q.count():
      return q[0]
    return None

  def next(self):
    q = Keg.objects.filter(site=self.site, start_time__gt=self.start_time).order_by('start_time')
    if q.count():
      return q[0]
    return None

  def GetStatsRecord(self):
    try:
      return KegStats.objects.get(keg=self)
    except KegStats.DoesNotExist:
      return None

  def GetStats(self):
    record = self.GetStatsRecord()
    if record:
      return record.stats
    return {}

  def RecomputeStats(self):
    self.stats.all().delete()
    last_d = self.drinks.valid().order_by('-start_time')
    if last_d:
      last_d[0]._UpdateKegStats()

  def Sessions(self):
    chunks = SessionChunk.objects.filter(keg=self).order_by('-start_time').select_related(depth=2)
    sessions = []
    sess = None
    for c in chunks:
      # Skip same sessions
      if c.session == sess:
        continue
      sess = c.session
      sessions.append(sess)
    return sessions

  def TopDrinkers(self):
    stats = self.GetStats()
    if not stats:
      return []
    ret = []
    entries = stats.get('volume_by_drinker', [])
    for entry in entries:
      username = str(entry.username)
      vol = entry.volume_ml
      try:
        user = User.objects.get(username=username)
      except User.DoesNotExist:
        continue  # should not happen
      ret.append((vol, user))
    ret.sort(reverse=True)
    return ret

  def __str__(self):
    return "Keg #%s - %s" % (self.id, self.type)

  site = models.ForeignKey(KegbotSite, related_name='kegs')
  seqn = models.PositiveIntegerField(editable=False)
  type = models.ForeignKey(bdb.BeerType)
  size = models.ForeignKey(KegSize)
  start_time = models.DateTimeField(default=datetime.datetime.now)
  end_time = models.DateTimeField(default=datetime.datetime.now)
  status = models.CharField(max_length=128, choices=(
     ('online', 'online'),
     ('offline', 'offline'),
     ('coming soon', 'coming soon')))
  description = models.CharField(max_length=256, blank=True, null=True)
  origcost = models.FloatField(default=0, blank=True, null=True)
  spilled_ml = models.FloatField(default=0)
  notes = models.TextField(blank=True, null=True,
      help_text='Private notes about this keg, viewable only by admins.')

def _keg_pre_save(sender, instance, **kwargs):
  keg = instance
  # We don't need to do anything if the keg is still online.
  if keg.status != 'offline':
    return

  # Determine first drink date & set keg start date to it if earlier.
  drinks = keg.drinks.valid().order_by('time')
  if drinks:
    drink = drinks[0]
    if drink.time < keg.start_time:
      keg.start_time = drink.time

  # Determine last drink date & set keg end date to it if later.
  drinks = keg.drinks.valid().order_by('-time')
  if drinks:
    drink = drinks[0]
    if drink.time > keg.end_time:
      keg.end_time = drink.time

pre_save.connect(_set_seqn_pre_save, sender=Keg)
pre_save.connect(_keg_pre_save, sender=Keg)

def _keg_post_save(sender, instance, **kwargs):
  keg = instance
  SystemEvent.ProcessKeg(keg)

post_save.connect(_keg_post_save, sender=Keg)


class Drink(models.Model):
  """ Table of drinks records """
  class Meta:
    unique_together = ('site', 'seqn')
    get_latest_by = 'time'
    ordering = ('-time',)

  @models.permalink
  def get_absolute_url(self):
    return ('kb-drink', (self.site.url(), str(self.seqn)))

  def ShortUrl(self):
    parts = [self.site.full_url()]
    parts.append('d')
    parts.append(str(self.seqn))
    return '/'.join(parts)

  def Volume(self):
    return units.Quantity(self.volume_ml)

  def calories(self):
    if not self.keg or not self.keg.type:
      return 0
    ounces = self.Volume().InOunces()
    return self.keg.type.calories_oz * ounces

  def __str__(self):
    return "Drink %s:%i by %s" % (self.site.name, self.seqn, self.user)

  def _UpdateSystemStats(self):
    stats, created = SystemStats.objects.get_or_create(site=self.site)
    stats.Update(self)

  def _UpdateUserStats(self):
    if self.user:
      stats, created = UserStats.objects.get_or_create(user=self.user, site=self.site)
      stats.Update(self)

  def _UpdateKegStats(self):
    if self.keg:
      stats, created = KegStats.objects.get_or_create(keg=self.keg, site=self.site)
      stats.Update(self)

  def _UpdateSessionStats(self):
    if self.session:
      stats, created = SessionStats.objects.get_or_create(session=self.session, site=self.site)
      stats.Update(self)

  def PostProcess(self):
    self._UpdateSystemStats()
    self._UpdateUserStats()
    self._UpdateKegStats()
    self._UpdateSessionStats()
    SystemEvent.ProcessDrink(self)

  objects = managers.DrinkManager()

  site = models.ForeignKey(KegbotSite, related_name='drinks')
  seqn = models.PositiveIntegerField(editable=False)

  # Ticks records the actual meter reading, which is never changed once
  # recorded.
  ticks = models.PositiveIntegerField()

  # Volume is the actual volume of the drink.  Its initial value is a function
  # of `ticks`, but it may be adjusted, eg due to calibration or mis-recording.
  volume_ml = models.FloatField()

  time = models.DateTimeField()
  duration = models.PositiveIntegerField(blank=True, default=0)
  user = models.ForeignKey(User, null=True, blank=True, related_name='drinks')
  keg = models.ForeignKey(Keg, null=True, blank=True, related_name='drinks')
  status = models.CharField(max_length=128, choices = (
     ('valid', 'valid'),
     ('invalid', 'invalid'),
     ('deleted', 'deleted'),
     ), default = 'valid')
  session = models.ForeignKey('DrinkingSession',
      related_name='drinks', null=True, blank=True, editable=False)
  auth_token = models.CharField(max_length=256, blank=True, null=True)
  shout = models.TextField(blank=True, null=True,
      help_text='Comment from the drinker at the time of the pour.')

pre_save.connect(_set_seqn_pre_save, sender=Drink)

class AuthenticationToken(models.Model):
  """A secret token to authenticate a user, optionally pin-protected."""
  class Meta:
    unique_together = (('site', 'seqn'), ('site', 'auth_device', 'token_value'))

  def __str__(self):
    ret = "%s: %s" % (self.auth_device, self.token_value)
    if self.user is not None:
      ret = "%s (%s)" % (ret, self.user.username)
    if self.nice_name:
      ret = "[%s] %s" % (self.nice_name, ret)
    return ret

  site = models.ForeignKey(KegbotSite, related_name='tokens')
  seqn = models.PositiveIntegerField(editable=False)
  auth_device = models.CharField(max_length=64)
  token_value = models.CharField(max_length=128)
  nice_name = models.CharField(max_length=256, blank=True, null=True,
      help_text='A human-readable alias for the token (eg "Guest Key").')
  pin = models.CharField(max_length=256, blank=True, null=True)
  user = models.ForeignKey(User, blank=True, null=True)
  enabled = models.BooleanField(default=True)
  created_time = models.DateTimeField(auto_now_add=True)
  expire_time = models.DateTimeField(blank=True, null=True)

  def IsAssigned(self):
    return self.user is not None

  def IsActive(self):
    if not self.enabled:
      return False
    if not self.expire_time:
      return True
    return datetime.datetime.now() < self.expire_time

def _auth_token_pre_save(sender, instance, **kwargs):
  if instance.auth_device in kb_common.AUTH_MODULE_NAMES_HEX_VALUES:
    instance.token_value = instance.token_value.lower()

pre_save.connect(_auth_token_pre_save, sender=AuthenticationToken)
pre_save.connect(_set_seqn_pre_save, sender=AuthenticationToken)

class _AbstractChunk(models.Model):
  class Meta:
    abstract = True
    get_latest_by = 'start_time'
    ordering = ('-start_time',)

  start_time = models.DateTimeField()
  end_time = models.DateTimeField()
  volume_ml = models.FloatField(default=0)

  def Duration(self):
    return self.end_time - self.start_time

  def _AddDrinkNoSave(self, drink):
    session_delta = drink.site.settings.GetSessionTimeoutDelta()
    session_end = drink.time + session_delta

    if self.start_time > drink.time:
      self.start_time = drink.time
    if self.end_time < session_end:
      self.end_time = session_end
    self.volume_ml += drink.volume_ml

  def AddDrink(self, drink):
    self._AddDrinkNoSave(drink)
    self.save()


class DrinkingSession(_AbstractChunk):
  """A collection of contiguous drinks. """
  class Meta:
    unique_together = ('site', 'seqn')
    get_latest_by = 'start_time'
    ordering = ('-start_time',)

  objects = managers.SessionManager()
  site = models.ForeignKey(KegbotSite, related_name='sessions')
  seqn = models.PositiveIntegerField(editable=False)
  name = models.CharField(max_length=256, blank=True, null=True)
  slug = AutoSlugField(populate_from='name', unique_with='site', blank=True,
      null=True)

  def __str__(self):
    return "Session #%s: %s" % (self.seqn, self.start_time)

  def RecomputeStats(self):
    self.stats.all().delete()
    try:
      last_d = self.drinks.valid().latest()
      last_d._UpdateSessionStats()
    except Drink.DoesNotExist:
      pass

  @models.permalink
  def get_absolute_url(self):
    if self.slug:
      slug = self.slug
    else:
      slug = 'session-%i' % self.seqn
    return ('kb-session',  (), {
      'kbsite_name' : self.site.url(),
      'year' : self.start_time.year,
      'month' : '%02i' % self.start_time.month,
      'day' : '%02i' % self.start_time.day,
      'seqn' : self.seqn,
      'slug' : slug})

  def GetStatsRecord(self):
    try:
      return SessionStats.objects.get(session=self)
    except SessionStats.DoesNotExist:
      return None

  def GetStats(self):
    record = self.GetStatsRecord()
    if record:
      return record.stats
    return {}

  def summarize_drinkers(self):
    def fmt(user):
      url = '/drinker/%s/' % (user.username,)
      return '<a href="%s">%s</a>' % (url, user.username)
    chunks = self.user_chunks.all().order_by('-volume_ml')
    users = tuple(c.user for c in chunks)
    names = tuple(fmt(u) for u in users if u)

    if None in users:
      guest_trailer = ' (and possibly others)'
    else:
      guest_trailer = ''

    num = len(names)
    if num == 0:
      return 'no known drinkers'
    elif num == 1:
      ret = names[0]
    elif num == 2:
      ret = '%s and %s' % names
    elif num == 3:
      ret = '%s, %s and %s' % names
    else:
      if guest_trailer:
        return '%s, %s and at least %i others' % (names[0], names[1], num-2)
      else:
        return '%s, %s and %i others' % (names[0], names[1], num-2)

    return '%s%s' % (ret, guest_trailer)

  def GetTitle(self):
    if self.name:
      return self.name
    else:
      return 'Session %i' % (self.seqn,)

  def AddDrink(self, drink):
    super(DrinkingSession, self).AddDrink(drink)
    session_delta = drink.site.settings.GetSessionTimeoutDelta()

    defaults = {
      'start_time': drink.time,
      'end_time': drink.time + session_delta,
    }

    # Update or create a SessionChunk.
    chunk, created = SessionChunk.objects.get_or_create(session=self,
        user=drink.user, keg=drink.keg, defaults=defaults)
    chunk.AddDrink(drink)

    # Update or create a UserSessionChunk.
    chunk, created = UserSessionChunk.objects.get_or_create(session=self,
        site=drink.site, user=drink.user, defaults=defaults)
    chunk.AddDrink(drink)

    # Update or create a KegSessionChunk.
    chunk, created = KegSessionChunk.objects.get_or_create(session=self,
        site=drink.site, keg=drink.keg, defaults=defaults)
    chunk.AddDrink(drink)

  def UserChunksByVolume(self):
    chunks = self.user_chunks.all().order_by('-volume_ml')
    return chunks

  def IsActiveNow(self):
    return self.IsActive(datetime.datetime.now())

  def IsActive(self, now):
    return self.end_time > now

  def Rebuild(self):
    self.volume_ml = 0
    self.chunks.all().delete()
    self.user_chunks.all().delete()
    self.keg_chunks.all().delete()

    drinks = self.drinks.valid()
    if not drinks:
      # TODO(mikey): cancel/delete the session entirely.  As it is, session will
      # remain a placeholder.
      return

    session_delta = self.site.settings.GetSessionTimeoutDelta()
    min_time = None
    max_time = None
    for d in drinks:
      self.AddDrink(d)
      if min_time is None or d.time < min_time:
        min_time = d.time
      if max_time is None or d.time > max_time:
        max_time = d.time
    self.start_time = min_time
    self.end_time = max_time + session_delta
    self.save()

  @classmethod
  def AssignSessionForDrink(cls, drink):
    # Return existing session if already assigned.
    if drink.session:
      return drink.session

    # Return last session if one already exists
    q = drink.site.sessions.all().order_by('-end_time')[:1]
    if q and q[0].IsActive(drink.time):
      session = q[0]
      session.AddDrink(drink)
      drink.session = session
      drink.save()
      return session

    # Create a new session
    session = cls(start_time=drink.time, end_time=drink.time,
        site=drink.site)
    session.save()
    session.AddDrink(drink)
    drink.session = session
    drink.save()
    return session

def _drinking_session_pre_save(sender, instance, **kwargs):
  session = instance
  if not session.name:
    session.name = 'Session %i' % session.seqn

  # NOTE(mikey): Clear the slug so that updates cause it to be recomputed by
  # AutoSlugField.  This could be spurious; is there a better way?
  session.slug = ''

pre_save.connect(_set_seqn_pre_save, sender=DrinkingSession)
pre_save.connect(_drinking_session_pre_save, sender=DrinkingSession)


class SessionChunk(_AbstractChunk):
  """A specific user and keg contribution to a session."""
  class Meta:
    unique_together = ('session', 'user', 'keg')
    get_latest_by = 'start_time'
    ordering = ('-start_time',)

  session = models.ForeignKey(DrinkingSession, related_name='chunks')
  user = models.ForeignKey(User, related_name='session_chunks', blank=True,
      null=True)
  keg = models.ForeignKey(Keg, related_name='session_chunks', blank=True,
      null=True)


class UserSessionChunk(_AbstractChunk):
  """A specific user's contribution to a session (spans all kegs)."""
  class Meta:
    unique_together = ('session', 'user')
    get_latest_by = 'start_time'
    ordering = ('-start_time',)

  site = models.ForeignKey(KegbotSite, related_name='user_chunks')
  session = models.ForeignKey(DrinkingSession, related_name='user_chunks')
  user = models.ForeignKey(User, related_name='user_session_chunks', blank=True,
      null=True)

  def GetTitle(self):
    return self.session.GetTitle()

  def GetDrinks(self):
    return self.session.drinks.filter(user=self.user).order_by('time')


class KegSessionChunk(_AbstractChunk):
  """A specific keg's contribution to a session (spans all users)."""
  class Meta:
    unique_together = ('session', 'keg')
    get_latest_by = 'start_time'
    ordering = ('-start_time',)

  objects = managers.SessionManager()
  site = models.ForeignKey(KegbotSite, related_name='keg_chunks')
  session = models.ForeignKey(DrinkingSession, related_name='keg_chunks')
  keg = models.ForeignKey(Keg, related_name='keg_session_chunks', blank=True,
      null=True)

  def GetTitle(self):
    return self.session.GetTitle()


class ThermoSensor(models.Model):
  class Meta:
    unique_together = ('site', 'seqn')

  site = models.ForeignKey(KegbotSite, related_name='thermosensors')
  seqn = models.PositiveIntegerField(editable=False)
  raw_name = models.CharField(max_length=256)
  nice_name = models.CharField(max_length=128)

  def __str__(self):
    return '%s (%s) ' % (self.nice_name, self.raw_name)

  def LastLog(self):
    try:
      return self.thermolog_set.latest()
    except Thermolog.DoesNotExist:
      return None

pre_save.connect(_set_seqn_pre_save, sender=ThermoSensor)


class Thermolog(models.Model):
  """ A log from an ITemperatureSensor device of periodic measurements. """
  class Meta:
    unique_together = ('site', 'seqn')
    get_latest_by = 'time'
    ordering = ('-time',)

  site = models.ForeignKey(KegbotSite, related_name='thermologs')
  seqn = models.PositiveIntegerField(editable=False)
  sensor = models.ForeignKey(ThermoSensor)
  temp = models.FloatField()
  time = models.DateTimeField()

  def __str__(self):
    return '%s %.2f C / %.2f F [%s]' % (self.sensor, self.TempC(),
        self.TempF(), self.time)

  def TempC(self):
    return self.temp

  def TempF(self):
    return util.CtoF(self.temp)

def _thermolog_post_save(sender, instance, **kwargs):
  daily_date = datetime.datetime(year=instance.time.year,
      month=instance.time.month,
      day=instance.time.day)
  defaults = {
      'site': instance.site,
      'num_readings': 1,
      'min_temp': instance.temp,
      'max_temp': instance.temp,
      'mean_temp': instance.temp,
  }
  daily_log, created = ThermoSummaryLog.objects.get_or_create(
      sensor=instance.sensor,
      period='daily',
      time=daily_date,
      defaults=defaults)

  if not created:
    new_mean = daily_log.num_readings * daily_log.mean_temp + instance.temp
    new_mean /= daily_log.num_readings + 1
    daily_log.mean_temp = new_mean

    daily_log.num_readings += 1

    if instance.temp > daily_log.max_temp:
      daily_log.max_temp = instance.temp
    if instance.temp < daily_log.min_temp:
      daily_log.min_temp = instance.temp

  daily_log.save()

  # Keep at least the most recent 24 hours, dropping any older entries.
  now = datetime.datetime.now()
  keep_time = now - datetime.timedelta(hours=24)
  old_entries = Thermolog.objects.filter(site=instance.site, time__lt=keep_time)
  old_entries.delete()

pre_save.connect(_set_seqn_pre_save, sender=Thermolog)
post_save.connect(_thermolog_post_save, sender=Thermolog)


class ThermoSummaryLog(models.Model):
  """A summarized temperature sensor log."""
  class Meta:
    unique_together = ('site', 'seqn')

  PERIOD_CHOICES = (
    ('daily', 'daily'),
  )
  site = models.ForeignKey(KegbotSite, related_name='thermosummarylogs')
  seqn = models.PositiveIntegerField(editable=False)
  sensor = models.ForeignKey(ThermoSensor)
  time = models.DateTimeField()
  period = models.CharField(max_length=64, choices=PERIOD_CHOICES,
      default='daily')
  num_readings = models.PositiveIntegerField()
  min_temp = models.FloatField()
  max_temp = models.FloatField()
  mean_temp = models.FloatField()

pre_save.connect(_set_seqn_pre_save, sender=ThermoSummaryLog)


class _StatsModel(models.Model):
  STATS_BUILDER = None

  class Meta:
    abstract = True

  def Update(self, drink, force=False):
    previous = None
    try:
      if not force and self.stats:
        previous = protoutil.DictToProtoMessage(self.stats, models_pb2.Stats())
    except TypeError, e:
      pass
    builder = self.STATS_BUILDER(drink, previous)
    self.stats = protoutil.ProtoMessageToDict(builder.Build())
    self.save()

  site = models.ForeignKey(KegbotSite)
  time = models.DateTimeField(default=datetime.datetime.now)
  stats = fields.JSONField()


class SystemStats(_StatsModel):
  STATS_BUILDER = stats.SystemStatsBuilder

  def __str__(self):
    return 'SystemStats for %s' % self.site


class UserStats(_StatsModel):
  class Meta:
    unique_together = ('site', 'user')
  STATS_BUILDER = stats.DrinkerStatsBuilder
  user = models.ForeignKey(User, blank=True, null=True, related_name='stats')

  def __str__(self):
    return 'UserStats for %s' % self.user


class KegStats(_StatsModel):
  STATS_BUILDER = stats.KegStatsBuilder
  keg = models.ForeignKey(Keg, unique=True, related_name='stats')
  completed = models.BooleanField(default=False)

  def __str__(self):
    return 'KegStats for %s' % self.keg


class SessionStats(_StatsModel):
  STATS_BUILDER = stats.SessionStatsBuilder
  session = models.ForeignKey(DrinkingSession, unique=True, related_name='stats')
  completed = models.BooleanField(default=False)

  def __str__(self):
    return 'SessionStats for %s' % self.session


class SystemEvent(models.Model):
  class Meta:
    ordering = ('-id',)
    get_latest_by = 'time'

  KINDS = (
      ('drink_poured', 'Drink poured'),
      ('session_started', 'Session started'),
      ('session_joined', 'User joined session'),
      ('keg_tapped', 'Keg tapped'),
      ('keg_ended', 'Keg ended'),
  )

  site = models.ForeignKey(KegbotSite, related_name='events')
  seqn = models.PositiveIntegerField(editable=False)
  kind = models.CharField(max_length=255, choices=KINDS,
      help_text='Type of event.')
  time = models.DateTimeField(help_text='Time of the event.')
  user = models.ForeignKey(User, blank=True, null=True,
      related_name='events',
      help_text='User responsible for the event, if any.')
  drink = models.ForeignKey(Drink, blank=True, null=True,
      related_name='events',
      help_text='Drink involved in the event, if any.')
  keg = models.ForeignKey(Keg, blank=True, null=True,
      related_name='events',
      help_text='Keg involved in the event, if any.')
  session = models.ForeignKey(DrinkingSession, blank=True, null=True,
      related_name='events',
      help_text='Session involved in the event, if any.')

  def __str__(self):
    if self.kind == 'drink_poured':
      ret = 'Drink %i poured' % self.drink.seqn
    elif self.kind == 'session_started':
      ret = 'Session %i started by drink %i' % (self.session.seqn,
          self.drink.seqn)
    elif self.kind == 'session_joined':
      ret = 'Session %i joined by %s (drink %i)' % (self.session.seqn,
          self.user.username, self.drink.seqn)
    elif self.kind == 'keg_tapped':
      ret = 'Keg %i tapped' % self.keg.seqn
    elif self.kind == 'keg_ended':
      ret = 'Keg %i ended' % self.keg.seqn
    else:
      ret = 'Unknown event type (%s)' % self.kind
    return 'Event %i: %s' % (self.seqn, ret)

  @classmethod
  def ProcessKeg(cls, keg):
    site = keg.site
    if keg.status == 'online':
      q = keg.events.filter(kind='keg_tapped')
      if q.count() == 0:
        e = keg.events.create(site=site, kind='keg_tapped', time=keg.start_time,
            keg=keg)
        e.save()

    if keg.status == 'offline':
      q = keg.events.filter(kind='keg_ended')
      if q.count() == 0:
        e = keg.events.create(site=site, kind='keg_ended', time=keg.end_time,
            keg=keg)
        e.save()

  @classmethod
  def ProcessDrink(cls, drink):
    keg = drink.keg
    session = drink.session
    site = drink.site
    user = drink.user

    if keg:
      q = keg.events.filter(kind='keg_tapped')
      if q.count() == 0:
        e = keg.events.create(site=site, kind='keg_tapped', time=drink.time,
            keg=keg, user=user, drink=drink, session=session)
        e.save()

    if session:
      q = session.events.filter(kind='session_started')
      if q.count() == 0:
        e = session.events.create(site=site, kind='session_started',
            time=session.start_time, drink=drink, user=user)
        e.save()

    if user:
      q = user.events.filter(kind='session_joined', session=session)
      if q.count() == 0:
        e = user.events.create(site=site, kind='session_joined',
            time=drink.time, session=session, drink=drink, user=user)
        e.save()

    q = drink.events.filter(kind='drink_poured')
    if q.count() == 0:
      e = drink.events.create(site=site, kind='drink_poured',
          time=drink.time, drink=drink, user=user, keg=keg,
          session=session)
      e.save()

pre_save.connect(_set_seqn_pre_save, sender=SystemEvent)


def _pics_file_name(instance, filename):
  rand_salt = random.randrange(0xffff)
  new_filename = '%04x-%s' % (rand_salt, filename)
  return os.path.join('pics', new_filename)

class Picture(models.Model):
  seqn = models.PositiveIntegerField(editable=False)
  site = models.ForeignKey(KegbotSite, related_name='pictures',
      blank=True, null=True,
      help_text='Site owning this picture')
  image = models.ImageField(upload_to=_pics_file_name,
      help_text='The image')

  resized = imagespecs.resized
  thumbnail = imagespecs.thumbnail
  small_resized = imagespecs.small_resized
  small_thumbnail = imagespecs.small_thumbnail

  time = models.DateTimeField(default=datetime.datetime.now)
  caption = models.TextField(blank=True, null=True,
      help_text='Caption for the picture')
  user = models.ForeignKey(User, blank=True, null=True,
      help_text='User this picture is associated with, if any')
  keg = models.ForeignKey(Keg, blank=True, null=True, related_name='pictures',
      help_text='Keg this picture is associated with, if any')
  session = models.ForeignKey(DrinkingSession, blank=True, null=True,
      on_delete=models.SET_NULL,
      related_name='pictures',
      help_text='Session this picture is associated with, if any')
  drink = models.ForeignKey(Drink, blank=True, null=True,
      related_name='pictures',
      help_text='Drink this picture is associated with, if any')

  def GetCaption(self):
    if self.caption:
      return self.caption
    elif self.drink:
      if self.user:
        return '%s pouring drink %s' % (self.user.username, self.drink.seqn)
      else:
        return 'An unknown drinker pouring drink %s' % (self.drink.seqn,)
    else:
      return ''

pre_save.connect(_set_seqn_pre_save, sender=Picture)

