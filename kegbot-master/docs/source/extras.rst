.. _kegbot-extras:

Extras and Add-Ons
==================

By now you've got a default Kegbot server running.  There are several more
features you can enable by installing and configuring optional components.

Task queue (Celery)
-------------------

Certain features, such as Twitter checkins and web hook support, require a
non-webserver process to run them in the background.  Kegbot uses `Celery
<http://celeryproject.org/>`_ as its task queue.

To install Celery and related dependencies::

  (kb) $ pip install Celery django-celery django-kombu
  (kb) $ kegbot-admin.py syncdb
  (kb) $ kegbot-admin.py migrate

Once Celery is installed, you can try running it in the foreground::

  (kb) $ kegbot-admin.py celeryd -E -v2

You should see the Celery welcome banner and some verbose log output.  When a
drink is poured, you should see Celery log some output a few seconds after the
drink is saved.

If everything is working correctly, cancel the process and restart celery in the
background::

  (kb) $ kegbot-admin celeryd_detach -E

