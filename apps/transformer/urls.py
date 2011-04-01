from django.conf.urls.defaults import patterns, include, url

urlpatterns = patterns('',

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    # url(r'^admin/', include(admin.site.urls)),
    
    
    (r'test/$', 'apps.transformer.views.test'),
    #(r'\'checksig/$', 'apps.transformer.views.checksig'),

    
    (r'.resize(?P<width>\d*)x(?P<height>\d*)\.*(?P<format>\w*)$', 'apps.transformer.views.resize'),
    (r'.crop(?P<width>\d*)x(?P<height>\d*)\.*(?P<format>\w*)$', 'apps.transformer.views.crop'),

    (r'^', 'apps.transformer.views.original'),

)
