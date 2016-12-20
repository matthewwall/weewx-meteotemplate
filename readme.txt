meteotemplate - weewx extension that sends data to a meteotemplate instance
Copyright 2016 Matthew Wall

===============================================================================
Installation

1) run the installer:

wee_extension --install weewx-meteotemplate.tgz

2) enter parameters in weewx.conf:

[StdRESTful]
    [[Meteotemplate]]
        host = HOSTNAME

3) restart weewx:

sudo /etc/init.d/weewx stop
sudo /etc/init.d/weewx start
