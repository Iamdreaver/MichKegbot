.. _configure-kegbot:

Configure Kegbot Server
=======================

In this section, you will point your new Kegbot Server installation to its database.

Run the Setup Wizard
--------------------

Kegbot Server needs a little bit of static configuration before it works.  At the
moment, Kegbot Server uses a `Django Settings file
<http://docs.djangoproject.com/en/dev/topics/settings/>`_ for all of its
configuration.  Mostly, you just need to tell Kegbot Server what kind of database to
use and where Kegbot Server will store files used by the webservice.

Kegbot will search for a settings file in two locations:

* ``~/.kegbot/local_settings.py``
* ``/etc/kegbot/local_settings.py``

You can use either location, but in these instructions we'll use `~/.kegbot/`.
The program ``setup-kegbot.py`` will help you:

* Configure Kegbot for the database you selected in the previous step;
* Create Kegbot's Media and Static Files directories;
* Install defaults into your new database.

Run the setup wizard::

	$ setup-kegbot.py

When finished, you should have a settings file in
``~/.kegbot/local_settings.py`` that you can examine.

About Media and Static Files
----------------------------

After running the wizard, two important settings should have been configured:
the *media* and *static files* directories.

**MEDIA_ROOT**
  This variable controls where Kegbot stores uploaded media: pictures added
  during account registration or pours, for example.

**STATIC_ROOT**
  This variable controls where Kegbot's static media is stored, such as built-in
  style sheets and images shown on the web page.

.. warning::
  **Never** place other content in ``STATIC_ROOT``, and always be sure it is set
  to a directory that Kegbot can completely overwrite.  For more information,
  see `Django's documentation for managing static files
  <https://docs.djangoproject.com/en/dev/howto/static-files/>`_.

