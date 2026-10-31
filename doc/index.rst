.. rt documentation master file, created by
   sphinx-quickstart on Thu Jan 10 16:31:25 2013.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to rt's documentation!
==============================

Contents:

.. toctree::
   :maxdepth: 1

   rest1
   rest2
   rest2_async
   common
   usage
   changelog
   exceptions
   glossary

.. csv-table:: Python version compatibility:
   :header: "Python", "rt"
   :widths: 15, 15

   "2.7", "< 2.0.0"
   ">= 3.5, <3.7", ">= 2.0.0, < 3.0.0"
   ">= 3.7", ">= 3.0.0, < 3.1.0"
   ">= 3.8", ">= 3.0.0, < 3.3.0"
   ">= 3.9", ">= 3.3.0, < 3.7.0"
   ">= 3.10", ">= 3.7.0"

.. note:: Please note that starting with the release of v3.7.0, this library requires Python version >= 3.10.
    See the *Python version compatibility* table above for more detailed information.

.. warning:: Although version 3.x still supports RT REST API version 1, it contains minor breaking changes.
    Please see the :doc:`changelog` in the documentation for details.

Get the rt module
=================

Using pip::

    pip install rt

Using project git repository::

    git clone https://github.com/python-rt/python-rt

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
