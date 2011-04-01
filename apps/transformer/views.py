from django.http import HttpResponseRedirect, HttpResponse, \
                        HttpResponseBadRequest,HttpResponseNotFound
import re
from PIL import Image
import boto
from django.conf import settings
import datetime
import os.path
from django.core.cache import cache, get_cache
import cStringIO

#------------------------------------------------------
# Logging parameters
import logging
import logging.handlers

LOG_FILENAME = '/var/log/httpd/scopeapp.log'

scopelog = logging.getLogger('scopelogger')
scopelog.setLevel(logging.INFO)
log_handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=1000000, backupCount=3)
log_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s [%(levelname)s] %(message)s"))
scopelog.addHandler(log_handler)
#------------------------------------------------------


def test(request):

    cache.set('test_key2', '2this is the cache value', 3600)

    # Sample code on how to switch caches    
    cdncache = get_cache('cdntrack')
    cdncache.set('test_key', 'this is a the cdn cache value', 3600)
    
    return HttpResponse("Hello, world: %s" % cache.get('test_key2'))
    
MAP_EXT_TO_MIME = {
    'jpg' : 'image/jpg',
    'png' : 'image/png',
}

MAP_EXT_TO_PIL_FORMAT = {
    'jpg' : 'JPEG',
    'png' : 'PNG', 
}

def original(request):

#    source_image = request.path[len(settings.PREPEND_PATH):]
#    local_file = get_image_from_storage(source_image)
#    if local_file:
#        return (send_file(local_file,'image/jpeg'))
#    else:
#        return HttpResponseNotFound()
 
#   return HttpResponse("Original test" )

    source_key = request.path[len(settings.PREPEND_PATH):]
    get_image_string_from_storage(source_key)
    
def crop(request,width,height,format):

    # Crop requires both parameters
    if not width or not height:
        HttpResponseBadRequest("Cropping requires both width and height")

    source_image = request.path[len(settings.PREPEND_PATH):request.path.rfind('.crop')]
    return image_operation(request, width, height, format, source_image, 'crop')

    #return HttpResponse("Crop test: %s x %s in format %s" % (width,height,format))
    
def resize(request,width,height,format):
    # Resize requires at least one parameter
    if not width and not height:
        HttpResponseBadRequest("Resizing requires width or height")
    
    source_image = request.path[len(settings.PREPEND_PATH):request.path.rfind('.resize')]
    return image_operation(request, width, height, format, source_image, 'resize')
    
    #return HttpResponse("Resize test: %s x %s in format %s.  Source_image=%s" % (width,height,format, source_image))

def image_operation(request,width,height,format,source_image,operation):
    
    # Check for valid supported formats
    if (format not in MAP_EXT_TO_MIME):
        return HttpResponseBadRequest("Non-supported image format")

    # Generate target key
    final_target = source_image + '.%s%sx%s.%s' % (operation,width,height,format)
    
    # check to see if key already exists in cache
    scopelog.info("image_operation: searching cache for final_target: %s" % final_target)
    image_string = cache.get(final_target)
    if image_string:
        # found this image in the cache. so serve it up
        im = Image.open(cStringIO.StringIO(image_string))
        scopelog.info("image_operation: cache hit!")
    else:
        # image is not in cache, so generate it
        scopelog.info("image_operation: cache miss!")

        #----------
        # First get the file from original storage
        
        # TODO: move this operation to utilize the cache as well        
        local_file = get_image_from_storage(source_image)
        if not local_file:
            return HttpResponseNotFound("File not registered with system")
        im = Image.open(local_file)
        im_width, im_height = im.size
     
        # Now actually generate the thumbnail
        if operation == 'resize':
            max_width = width or im_width
            max_height = height or im_height
            
            # Check for tiny dimensions
            if max_width < 3 or max_height < 3:
                return HttpResponseBadRequest("Must have dimensions greater than or equal to 3 pixels")
    
            size = [int(max_width),int(max_height)]
            im.thumbnail(size, Image.ANTIALIAS)
            
        elif operation == 'crop':
            image_ratio = float(im_width) / float(im_height)
            # Crop always requires two parameters so we're assuming non-zero
            # parameters in this section
            
            # For cropping, we have to figure out which dimension (w or h) will
            # fill the cropping box requested by client
            request_ratio = float(width)/float(height)
            if request_ratio > image_ratio:
                # cropping box is wider than original image
                # so use image width and calculate height            
                crop_width = im_width
                crop_height = crop_width / request_ratio
                x_offset = 0
                y_offset = float(im_height - crop_height) / 2
            else:
                # cropping box is taller than original image
                # so use image height and calculate width            
                crop_height = im_height
                crop_width = crop_height * request_ratio
                x_offset = float(im_width - crop_width) / 2
                y_offset = 0

            # now that we've calculated the parameters, let's use them
            # to get the correct data from the original image
            im = im.crop((x_offset,   y_offset,
                          x_offset+int(crop_width), y_offset+int(crop_height)))

            # We have the correctly cropped portion of the original image,
            # now size it the desired dimensions
            size = [int(width),int(height)]
            im.thumbnail(size, Image.ANTIALIAS)
        else:
            return HttpResponseBadRequest("Unsupported image operation")
            
        # now put the image into the file cache
        scopelog.info("image_operation: writing cache for final_target: %s" % final_target)
        
        # PIL Images are not pickle-able so we have to use cStringIO to
        # create the serialization to store it in the cache
        stringIO = cStringIO.StringIO()
        im.save(stringIO, MAP_EXT_TO_PIL_FORMAT[format])
        cache.set(final_target, stringIO.getvalue())
        stringIO.close()

    # these lines stream the file directly from the image store
    response = HttpResponse(mimetype=MAP_EXT_TO_MIME[format])
    im.save(response, MAP_EXT_TO_PIL_FORMAT[format])
    return response


def get_image_string_from_storage(source_key):
        
    # connect to S3 using the keys from the settings file    
    conn = boto.connect_s3(settings.AWS_ACCESS_KEY,settings.AWS_SECRET_KEY)
    bucket = conn.get_bucket(settings.AWS_BUCKET)
    key = bucket.get_key(source_key)

    if not key:
        return None

    image_stream = cStringIO.StringIO()

    # Pull the file down to the local disk    
    key.get_contents_to_file(image_stream)
    
    return image_stream
    

def get_image_from_storage(source_file):
        
    # get the base storage location and strip any trailing slashes
    # just in case they were added
    base_storage_dir = (settings.BASE_DIR_TEMP_IMAGE_STORAGE).rstrip('/')
    now = datetime.datetime.now()
    
    # create the target storage directory - one per month to allow
    # rotation to clean up old images.
    time_storage_dir = base_storage_dir + '/' + str(now.year) + '-' + str(now.month) + '/'

    # Now add on the source file name (and potentially path and create that)
    # and ensure to strip off the first slash on the source file if it exists
    target_storage_dir = os.path.dirname(time_storage_dir + source_file.lstrip('/'))
    if not os.path.exists(target_storage_dir):
        os.makedirs(target_storage_dir)
    
    # Create final filename to write S3 contents into    
    target_storage_file = time_storage_dir + source_file.lstrip('/')

    # connect to S3 using the keys from the settings file    
    conn = boto.connect_s3(settings.AWS_ACCESS_KEY,settings.AWS_SECRET_KEY)
    bucket = conn.get_bucket(settings.AWS_BUCKET)
    key = bucket.get_key(source_file)

    if not key:
        return None

    # Pull the file down to the local disk    
    key.get_contents_to_filename(target_storage_file)
    
    return target_storage_file
    
#-----------------------------------------------------------------
# Taken from Django Snippets: Send large files through Django, and how to generate Zip files
#-----------------------------------------------------------------
#
# http://djangosnippets.org/snippets/365/
#
#Author:jcrocholl Posted:August 12, 2007 Language:Python Django Version:.96
# Modifed by ERoman, March 30,2011
#

import os, tempfile, zipfile
from django.http import HttpResponse
from django.core.servers.basehttp import FileWrapper

def send_file(filename, mime_type=None, file_extension=None):
    """                                                                         
    Send a file through Django without loading the whole file into              
    memory at once. The FileWrapper will turn the file object into an           
    iterator for chunks of 8KB.                                                 
    """
    #
    # Use this to determine returned mime-type
    #
    sending_mime_type = None
    if mime_type:
        # use this if passed in as first choice
        sending_mime_type = mime_type
    else:
        if not file_extension:
            # So the calling function did not give us the extension,
            # so we pull from the file name given
            (dummy, file_extension) = os.path.splitext(filename)
        
        file_extension = file_extension.lower()
        sending_mime_type = MAP_EXT_TO_MIME[file_extension]
    
    wrapper = FileWrapper(file(filename))
    response = HttpResponse(wrapper, content_type=sending_mime_type)
    response['Content-Length'] = os.path.getsize(filename)
    return response

