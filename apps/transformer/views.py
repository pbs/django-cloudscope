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

# This dict is used to map the outgoing file format
# and could be very extensive.  So that original images
# of all kinds can be streamed if no xform is necessary
MAP_EXT_TO_MIME = {
    'jpg' : 'image/jpg',
    'png' : 'image/png',
}

# This dict is used to list the suported transform formats
# by PIL
MAP_EXT_TO_PIL_FORMAT = {
    'jpg' : 'JPEG',
    'png' : 'PNG', 
}

def original(request):

    # determine what the source key request is
    source_key = request.path[len(settings.PREPEND_PATH):]
    format = source_key[source_key.rfind('.')+1:]
    
    # Check for valid supported formats
    if (format not in MAP_EXT_TO_MIME):
        return HttpResponseBadRequest("Non-supported image format")
        
    im = get_image_object_from_storage(source_key)
    if not im:
        return HttpResponseNotFound("File not registered with system")

    # these lines stream the file directly from the image store
    response = HttpResponse(mimetype=MAP_EXT_TO_MIME[format])
    im.save(response, MAP_EXT_TO_PIL_FORMAT[format])
    return response

    
def crop(request,width,height,format):

    # Crop requires both parameters
    if not width or not height:
        HttpResponseBadRequest("Cropping requires both width and height")

    # extract the original file without the crop modifier
    source_image = request.path[len(settings.PREPEND_PATH):request.path.rfind('.crop')]
    return image_operation(request, width, height, format, source_image, 'crop')
    
def resize(request,width,height,format):
    # Resize requires at least one parameter
    if not width and not height:
        HttpResponseBadRequest("Resizing requires width or height")
    
    # extract the original file without the resize modifier
    source_image = request.path[len(settings.PREPEND_PATH):request.path.rfind('.resize')]
    return image_operation(request, width, height, format, source_image, 'resize')
    
def image_operation(request,width,height,format,source_image,operation):
    
    # Check for valid supported formats
    if (format not in MAP_EXT_TO_PIL_FORMAT):
        return HttpResponseBadRequest("Non-supported image format")

    # Generate target key for cached storage
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
        im = get_image_object_from_storage(source_image)
        if not im:
            return HttpResponseNotFound("File not registered with system")
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


def get_image_object_from_storage(source_key):
    
    origcache = get_cache('original')

    image_string = origcache.get(source_key)
    if image_string:
        # found this image in the cache. so serve it up
        im = Image.open(cStringIO.StringIO(image_string))
        scopelog.info("get_image_object_from_storage: cache hit!")
    else:
        scopelog.info("get_image_object_from_storage: cache miss!")
    
        # connect to S3 using the keys from the settings file
        conn = boto.connect_s3(settings.AWS_ACCESS_KEY,settings.AWS_SECRET_KEY)
        bucket = conn.get_bucket(settings.AWS_BUCKET)
        key = bucket.get_key(source_key)
    
        if not key:
            return None
    
        image_stream = cStringIO.StringIO()
    
        # Pull the file down to the local disk    
        key.get_contents_to_file(image_stream)
        # rewind the current pointer for the stream
        image_stream.seek(0)
        im = Image.open(image_stream)

        # now put the image into the original file cache
        scopelog.info("get_image_object_from_storage: writing cache for final_target: %s" % source_key)
        
        # reset our pointer again to write out the data
        image_stream.seek(0)
        origcache.set(source_key, image_stream.getvalue())

    return im    

