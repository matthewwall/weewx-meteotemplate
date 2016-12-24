# installer for meteotemplate
# Copyright 2016 Matthew Wall

from setup import ExtensionInstaller

def loader():
    return MeteotemplateInstaller()

class MeteotemplateInstaller(ExtensionInstaller):
    def __init__(self):
        super(MeteotemplateInstaller, self).__init__(
            version="0.1rc1",
            name='meteotemplate',
            description='Upload weather data to Meteotemplate.',
            author="Matthew Wall",
            author_email="mwall@users.sourceforge.net",
            restful_services='user.meteotemplate.Meteotemplate',
            config={
                'StdRESTful': {
                    'Meteotemplate': {
                        'host': 'INSERT_HOST_HERE',
                        'password': 'INSERT_PASSWORD_HERE'}}},
            files=[('bin/user', ['bin/user/meteotemplate.py'])]
            )
