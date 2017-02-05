#!/usr/bin/env python
# Copyright 2016-2017 Matthew Wall
# Licensed under the terms of the GPLv3

"""
Meteotemplate is a weather website system written in PHP by Jachym.

http://meteotemplate.com

This is a weewx extension that uploads data to a Meteotemplate server.  It uses
the API described in the meteotemplate wiki:

http://www.meteotemplate.com/web/wiki/wikiAPI.php

More specifically, this extension works with the following API specification:

URL: http[s]://TEMPLATE_ROOT/api.php

Parameters:
  PASS - the "update password" in meteotemplate settings
  U - datetime as epoch
  T - temperature (C)
  H - humidity (%)
  P - pressure (mbar)
  W - wind speed (km/h)
  G - wind gust (km/h)
  B - wind direction (0-359)
  R - daily cumulative rain (mm since midnight)
  RR - current rain rate (mm/h)
  S - solar radiation (W/m^2)
  UV - ultraviolet index
  TIN - indoor temperature (C)
  HIN - indoor humidity (%)

A parameter is ignored if:
 - it is not provided in the URL
 - it is blank (e.g., T=&H=&P=)
 - is set to null (e.g., T=null&H=null)

Each request must contain PASS, U, and at least one parameter.

Data can be sent at any interval.  If the interval is shorter than 5 minutes,
data will be cached then aggregated.  The meteotemplate database is updated
every 5 minutes.
"""

import Queue
from distutils.version import StrictVersion
import sys
import syslog
import time
import urllib
import urllib2

import weewx
import weewx.restx
import weewx.units
from weeutil.weeutil import to_bool, accumulateLeaves, startOfDay

VERSION = "0.3"

REQUIRED_WEEWX = "3.5.0"
if StrictVersion(weewx.__version__) < StrictVersion(REQUIRED_WEEWX):
    raise weewx.UnsupportedFeature("weewx %s or greater is required, found %s"
                                   % (REQUIRED_WEEWX, weewx.__version__))

def logmsg(level, msg):
    syslog.syslog(level, 'restx: Meteotemplate: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)


class Meteotemplate(weewx.restx.StdRESTbase):
    def __init__(self, engine, cfg_dict):
        """This service recognizes standard restful options plus the following:

        Required parameters:

        host: name or ip address of server hosting meteotemplate

        Optional parameters:

        server_url: full URL to the meteotemplate ingest script
        Default is None
        """
        super(Meteotemplate, self).__init__(engine, cfg_dict)        
        loginf("service version is %s" % VERSION)
        try:
            site_dict = cfg_dict['StdRESTful']['Meteotemplate']
            site_dict = accumulateLeaves(site_dict, max_level=1)
            site_dict['password']
        except KeyError, e:
            logerr("Data will not be uploaded: Missing option %s" % e)
            return

        host = site_dict.pop('host', 'localhost')
        if site_dict.get('server_url', None) is None:
            site_dict['server_url'] = 'http://%s/api.php' % host

        try:
            _mgr_dict = weewx.manager.get_manager_dict_from_config(
                config_dict, 'wx_binding')
            site_dict['manager_dict'] = _mgr_dict
        except weewx.UnknownBinding:
            pass

        self._queue = Queue.Queue()
        try:
            self._thread = MeteotemplateThread(self._queue, **site_dict)
        except weewx.ViolatedPrecondition, e:
            loginf("Data will not be posted: %s" % e)
            return

        self._thread.start()
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)
        loginf("Data will be uploaded to %s" % site_dict['server_url'])

    def new_archive_record(self, event):
        self._queue.put(event.record)


class MeteotemplateThread(weewx.restx.RESTThread):

    def __init__(self, queue, password, server_url, skip_upload=False,
                 manager_dict=None,
                 post_interval=None, max_backlog=sys.maxint, stale=None,
                 log_success=True, log_failure=True,
                 timeout=60, max_tries=3, retry_wait=5):
        super(MeteotemplateThread, self).__init__(
            queue, protocol_name='Meteotemplate', manager_dict=manager_dict,
            post_interval=post_interval, max_backlog=max_backlog, stale=stale,
            log_success=log_success, log_failure=log_failure,
            max_tries=max_tries, timeout=timeout, retry_wait=retry_wait)
        self.server_url = server_url
        self.password = password
        self.skip_upload = to_bool(skip_upload)

    def process_record(self, record, dbm):
        if dbm:
            record = self.get_record(record, dbm)
        url = self.get_url(record)
        if weewx.debug >= 2:
            logdbg('url: %s' % url)
        if self.skip_upload:
            raise AbortedPost()
        req = urllib2.Request(url)
        req.add_header("User-Agent", "weewx/%s" % weewx.__version__)
        self.post_with_retries(req)

    FIELD_MAP = {
        'T': 'outTemp', # degree_C
        'H': 'outHumidity', # percent
        'P': 'barometer', # mbar
        'W': 'windSpeed', # km/h
        'G': 'windGust', # km/h
        'B': 'windDir', # degree_compass
        'RR': 'rainRate', # mm/h
        'R': 'dayRain', # mm
        'S': 'radiation', # W/m^2
        'UV': 'UV',
        'TIN': 'inTemp', # degree_C
        'HIN': 'inHumidity'}

    def get_url(self, record):
        record = weewx.units.to_std_system(record, weewx.METRIC)
        if 'dayRain' in record:
            record['dayRain'] *= 10.0 # convert to mm
        if 'rainRate' in record:
            record['rainRate'] *= 10.0 # convert to mm/h
        parts = dict()
        parts['PASS'] = self.password
        parts['U'] = record['dateTime']
        for k in self.FIELD_MAP:
            if (self.FIELD_MAP[k] in record and
                record[self.FIELD_MAP[k]] is not None):
                parts[k] = record.get(self.FIELD_MAP[k])
        return "%s?%s" % (self.server_url, urllib.urlencode(parts))


# Use this hook to test the uploader:
#   PYTHONPATH=bin python bin/user/meteotemplate.py

if __name__ == "__main__":
    weewx.debug = 2
    queue = Queue.Queue()
    t = MeteotemplateThread(
        queue, manager_dict=None, password='abc123',
        server_url='http://localhost/api.php')
    t.process_record({'dateTime': int(time.time() + 0.5),
                      'usUnits': weewx.US,
                      'outTemp': 32.5,
                      'inTemp': 75.8,
                      'outHumidity': 24}, None)
