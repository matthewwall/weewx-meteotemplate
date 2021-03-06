# installer for meteotemplate extension
# Copyright 2016-2020 Matthew Wall
# Distributed under terms of the GPLv3

from weecfg.extension import ExtensionInstaller

def loader():
    return MeteotemplateInstaller()

class MeteotemplateInstaller(ExtensionInstaller):
    def __init__(self):
        super(MeteotemplateInstaller, self).__init__(
            version="0.10",
            name='meteotemplate',
            description='Upload weather data to Meteotemplate.',
            author="Matthew Wall",
            author_email="mwall@users.sourceforge.net",
            restful_services='user.meteotemplate.Meteotemplate',
            config={
                'StdRESTful': {
                    'Meteotemplate': {
                        'server_url': 'INSERT_SERVER_URL_HERE',
                        'password': 'INSERT_PASSWORD_HERE'}}},
            files=[('bin/user', ['bin/user/meteotemplate.py'])]
            )
