#!/usr/bin/env python
# Copyright 2016-2020 Matthew Wall
# Licensed under the terms of the GPLv3

"""
Meteotemplate is a weather website system written in PHP by Jachym.

http://meteotemplate.com

This is a weewx extension that uploads data to a Meteotemplate server.  It uses
the API described in the meteotemplate wiki:

http://www.meteotemplate.com/web/wiki/wikiAPI.php

The set of fields actually sent depends on the sensors available and the way
the hardware sends data from those fields.

More specifically, this extension works with the following API specification:

URL: http[s]://TEMPLATE_ROOT/api.php

Parameters:
  PASS - the "update password" in meteotemplate settings
  U - datetime as epoch
  T - temperature (C)
  H - humidity (%)
  P - barometer (mbar)
  W - wind speed (km/h)
  G - wind gust (km/h)
  B - wind direction (0-359)
  R - daily cumulative rain (mm since midnight)
  RR - current rain rate (mm/h)
  S - solar radiation (W/m^2)
  UV - ultraviolet index
  TIN - indoor temperature (C)
  HIN - indoor humidity (%)
  ...

A parameter is ignored if:
 - it is not provided in the URL
 - it is blank (e.g., T=&H=&P=)
 - is set to null (e.g., T=null&H=null)

Each request must contain PASS, U, and at least one parameter.

Data can be sent at any interval.  If the interval is shorter than 5 minutes,
data will be cached then aggregated.  The meteotemplate database is updated
every 5 minutes.

Battery status is handled properly for battery status fields in the default
schema.  Battery voltages are not included (the meteotemplate API has no
provision for battery voltage).
"""

try:
    # Python 3
    import queue
except ImportError:
    # Python 2
    import Queue as queue
import sys
import time
from distutils.version import StrictVersion

try:
    # Python 3
    from urllib.parse import urlencode
except ImportError:
    # Python 2
    from urllib import urlencode

import weewx
import weewx.restx
import weewx.units
from weeutil.weeutil import to_bool, list_as_string

VERSION = "0.10"

REQUIRED_WEEWX = "3.5.0"
if StrictVersion(weewx.__version__) < StrictVersion(REQUIRED_WEEWX):
    raise weewx.UnsupportedFeature("weewx %s or greater is required, found %s"
                                   % (REQUIRED_WEEWX, weewx.__version__))

try:
    # Test for new-style weewx logging by trying to import weeutil.logger
    import weeutil.logger
    import logging
    log = logging.getLogger(__name__)

    def logdbg(msg):
        log.debug(msg)

    def loginf(msg):
        log.info(msg)

    def logerr(msg):
        log.error(msg)

except ImportError:
    # Old-style weewx logging
    import syslog

    def logmsg(level, msg):
        syslog.syslog(level, 'meteotemplate: %s' % msg)

    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)

    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)

    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)


class Meteotemplate(weewx.restx.StdRESTbase):
    DEFAULT_URL = 'http://localhost/template/api.php'

    def __init__(self, engine, cfg_dict):
        """This service recognizes standard restful options plus the following:

        Parameters:

        password: the shared key for uploading data

        server_url: full URL to the meteotemplate ingest script
        """
        super(Meteotemplate, self).__init__(engine, cfg_dict)
        loginf("service version is %s" % VERSION)

        site_dict = weewx.restx.get_site_dict(cfg_dict, 'Meteotemplate', 'password')
        if site_dict is None:
            return

        binding = list_as_string(site_dict.pop('binding', 'archive')).lower()

        try:
            site_dict['manager_dict'] = weewx.manager.get_manager_dict_from_config(cfg_dict, 'wx_binding')
        except weewx.UnknownBinding:
            pass

        self._queue = queue.Queue()
        self._thread = MeteotemplateThread(self._queue, **site_dict)
        self._thread.start()
        if 'loop' in binding:
            self.bind(weewx.NEW_LOOP_PACKET, self.handle_new_loop)
        if 'archive' in binding:
            self.bind(weewx.NEW_ARCHIVE_RECORD, self.handle_new_archive)

    def handle_new_loop(self, event):
        self._queue.put(event.packet)

    def handle_new_archive(self, event):
        self._queue.put(event.record)


class MeteotemplateThread(weewx.restx.RESTThread):

    def __init__(self, q, password, server_url=Meteotemplate.DEFAULT_URL, skip_upload=False,
                 manager_dict=None,
                 post_interval=None, max_backlog=sys.maxsize, stale=None,
                 log_success=True, log_failure=True,
                 timeout=60, max_tries=3, retry_wait=5):
        super(MeteotemplateThread, self).__init__(
            q, protocol_name='Meteotemplate', manager_dict=manager_dict,
            post_interval=post_interval, max_backlog=max_backlog, stale=stale,
            log_success=log_success, log_failure=log_failure,
            max_tries=max_tries, timeout=timeout, retry_wait=retry_wait)
        self.server_url = server_url
        self.password = password
        self.skip_upload = to_bool(skip_upload)
        self.field_map = self.create_default_field_map()
        # FIXME: make field map changes available via config file
        loginf("Data will be uploaded to %s" % self.server_url)

    def check_response(self, response):
        txt = response.read().decode()
        if txt != 'Success':
            raise weewx.restx.FailedPost("Server returned '%s'" % txt)

    def format_url(self, record):
        record = weewx.units.to_std_system(record, weewx.METRIC)
        if 'dayRain' in record and record['dayRain'] is not None:
            record['dayRain'] *= 10.0 # convert to mm
        if 'rainRate' in record and record['rainRate'] is not None:
            record['rainRate'] *= 10.0 # convert to mm/h
        parts = dict()
        parts['PASS'] = self.password
        parts['U'] = record['dateTime']
        parts['SW'] = "weewx-%s" % weewx.__version__
        for k in self.field_map:
            if (self.field_map[k][0] in record and
                    record[self.field_map[k][0]] is not None):
                parts[k] = self._fmt(record.get(self.field_map[k][0]),
                                     self.field_map[k][1])
        return "%s?%s" % (self.server_url, urlencode(parts))

    @staticmethod
    def _fmt(x, places=3):
        fmt = "%%.%df" % places
        try:
            return fmt % x
        except TypeError:
            pass
        return x

    @staticmethod
    def create_default_field_map():
        fm = {
            'T': ('outTemp', 2), # degree_C
            'H': ('outHumidity', 1), # percent
            'P': ('barometer', 3), # mbar
            'UGP': ('pressure', 3), # mbar
            'W': ('windSpeed', 2), # km/h
            'G': ('windGust', 2), # km/h
            'B': ('windDir', 0), # degree_compass
            'RR': ('rainRate', 3), # mm/h
            'R': ('dayRain', 3), # mm
            'S': ('radiation', 3), # W/m^2
            'UV': ('UV', 0),
            'TIN': ('inTemp', 2), # degree_C
            'HIN': ('inHumidity', 1), # percent
            'SN': ('daySnow', 3), # mm
            'SD': ('snowDepth', 3), # mm
            'L': ('lightning', 0),
            'NL': ('noise', 2)} # dB

        for i in range(1, 9):
            fm['T%d' % i] = ('extraTemp%d' % i, 2) # degree_C
            fm['H%d' % i] = ('extraHumid%d' % i, 1) # percent
            fm['TS%d' % i] = ('soilTemp%d' % i, 2) # degree_C
            fm['TSD%d' % i] = ('soilTempDepth%d' % i, 2) # cm
            fm['LW%d' % i] = ('leafWet%d' % i, 1)
            fm['LT%d' % i] = ('leafTemp%d' % i, 2) # degree_C
            fm['SM%d' % i] = ('soilMoist%d' % i, 1)
            fm['CO2_%d' % i] = ('co2_%d' % i, 3) # ppm
            fm['NO2_%d' % i] = ('no2_%d' % i, 3) # ppm
            fm['CO_%d' % i] = ('co_%d' % i, 3) # ppm
            fm['SO2_%d' % i] = ('so2_%d' % i, 3) # ppb
            fm['O3_%d' % i] = ('o3_%d' % i, 3) # ppb
            fm['pp%d' % i] = ('pp%d' % i, 3) # ug/m^3

        fm['TXBAT'] = ('txBatteryStatus', 0)
        fm['WBAT'] = ('windBatteryStatus', 0)
        fm['RBAT'] = ('rainBatteryStatus', 0)
        fm['TBAT'] = ('outTempBatteryStatus', 0)
        fm['TINBAT'] = ('inTempBatteryStatus', 0)
        return fm


# Do direct testing of this extension like this:
#   PYTHONPATH=WEEWX_BINDIR python WEEWX_BINDIR/user/meteotemplate.py

if __name__ == "__main__":
    import optparse

    weewx.debug = 2

    try:
        # WeeWX V4 logging
        weeutil.logger.setup('meteotemplate', {})
    except NameError:
        # WeeWX V3 logging
        syslog.openlog('meteotemplate', syslog.LOG_PID | syslog.LOG_CONS)
        syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))

    usage = """%prog [--url URL] [--pw password] [--version] [--help]"""

    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--version', dest='version', action='store_true',
                      help='display driver version')
    parser.add_option('--url', dest='url', default=Meteotemplate.DEFAULT_URL,
                      help='full URL to the server script')
    parser.add_option('--pw', dest='pw', help='upload password')
    (options, args) = parser.parse_args()

    if options.version:
        print("meteotemplate uploader version %s" % VERSION)
        exit(0)

    print("uploading to %s" % options.url)
    q = queue.Queue()
    t = MeteotemplateThread(q, manager_dict=None, password=options.pw, server_url=options.url)
    t.start()
    q.put({'dateTime': int(time.time() + 0.5),
           'usUnits': weewx.US,
           'outTemp': 32.5,
           'inTemp': 75.8,
           'outHumidity': 24})
    q.put(None)
    t.join(20)
