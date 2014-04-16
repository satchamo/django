from __future__ import unicode_literals

import mimetypes
from os import path
import unittest

from django.conf.urls.static import static
from django.http import HttpResponseNotModified
from django.test import SimpleTestCase, override_settings
from django.utils.http import http_date
from django.views.static import was_modified_since, RangedFileReader

from .. import urls
from ..urls import media_dir


@override_settings(DEBUG=True, ROOT_URLCONF='view_tests.urls')
class StaticTests(SimpleTestCase):
    """Tests django views in django/views/static.py"""

    prefix = 'site_media'

    def test_serve(self):
        "The static view can serve static media"
        media_files = ['file.txt', 'file.txt.gz']
        for filename in media_files:
            response = self.client.get('/%s/%s' % (self.prefix, filename))
            response_content = b''.join(response)
            file_path = path.join(media_dir, filename)
            with open(file_path, 'rb') as fp:
                self.assertEqual(fp.read(), response_content)
            self.assertEqual(len(response_content), int(response['Content-Length']))
            self.assertEqual(mimetypes.guess_type(file_path)[1], response.get('Content-Encoding', None))

    def test_unknown_mime_type(self):
        response = self.client.get('/%s/file.unknown' % self.prefix)
        self.assertEqual('application/octet-stream', response['Content-Type'])

    def test_copes_with_empty_path_component(self):
        file_name = 'file.txt'
        response = self.client.get('/%s//%s' % (self.prefix, file_name))
        response_content = b''.join(response)
        with open(path.join(media_dir, file_name), 'rb') as fp:
            self.assertEqual(fp.read(), response_content)

    def test_is_modified_since(self):
        file_name = 'file.txt'
        response = self.client.get('/%s/%s' % (self.prefix, file_name),
            HTTP_IF_MODIFIED_SINCE='Thu, 1 Jan 1970 00:00:00 GMT')
        response_content = b''.join(response)
        with open(path.join(media_dir, file_name), 'rb') as fp:
            self.assertEqual(fp.read(), response_content)

    def test_not_modified_since(self):
        file_name = 'file.txt'
        response = self.client.get(
            '/%s/%s' % (self.prefix, file_name),
            HTTP_IF_MODIFIED_SINCE='Mon, 18 Jan 2038 05:14:07 GMT'
            # This is 24h before max Unix time. Remember to fix Django and
            # update this test well before 2038 :)
        )
        self.assertIsInstance(response, HttpResponseNotModified)

    def test_invalid_if_modified_since(self):
        """Handle bogus If-Modified-Since values gracefully

        Assume that a file is modified since an invalid timestamp as per RFC
        2616, section 14.25.
        """
        file_name = 'file.txt'
        invalid_date = 'Mon, 28 May 999999999999 28:25:26 GMT'
        response = self.client.get('/%s/%s' % (self.prefix, file_name),
                                   HTTP_IF_MODIFIED_SINCE=invalid_date)
        response_content = b''.join(response)
        with open(path.join(media_dir, file_name), 'rb') as fp:
            self.assertEqual(fp.read(), response_content)
        self.assertEqual(len(response_content), int(response['Content-Length']))

    def test_invalid_if_modified_since2(self):
        """Handle even more bogus If-Modified-Since values gracefully

        Assume that a file is modified since an invalid timestamp as per RFC
        2616, section 14.25.
        """
        file_name = 'file.txt'
        invalid_date = ': 1291108438, Wed, 20 Oct 2010 14:05:00 GMT'
        response = self.client.get('/%s/%s' % (self.prefix, file_name),
                                   HTTP_IF_MODIFIED_SINCE=invalid_date)
        response_content = b''.join(response)
        with open(path.join(media_dir, file_name), 'rb') as fp:
            self.assertEqual(fp.read(), response_content)
        self.assertEqual(len(response_content), int(response['Content-Length']))

    def test_404(self):
        response = self.client.get('/%s/non_existing_resource' % self.prefix)
        self.assertEqual(404, response.status_code)

    def test_accept_ranges(self):
        response = self.client.get('/%s/%s' % (self.prefix, "file.txt"))
        self.assertEqual(response['Accept-Ranges'], "bytes")

    def test_syntactically_invalid_ranges(self):
        """
        Test that a syntactically invalid byte range header is ignored and the
        response gives back the whole resource as per RFC 2616, section 14.35.1
        """
        content = open(path.join(media_dir, "file.txt")).read()
        invalid = ["megabytes=1-2", "bytes=", "bytes=3-2", "bytes=--5", "units", "bytes=-,"]
        for range_ in invalid:
            response = self.client.get('/%s/%s' % (self.prefix, "file.txt"), HTTP_RANGE=range_)
            self.assertEqual(content, b''.join(response))

    def test_unsatisfiable_range(self):
        """Test that an unsatisfiable range results in a 416 HTTP status code"""
        content = open(path.join(media_dir, "file.txt")).read()
        # since byte ranges are *inclusive*, 0 to len(content) would be unsatisfiable
        response = self.client.get('/%s/%s' % (self.prefix, "file.txt"), HTTP_RANGE="bytes=0-%d" % len(content))
        self.assertEqual(response.status_code, 416)

    def test_ranges(self):
        # set the block size to something small so we do multiple iterations in
        # the RangedFileReader class
        original_block_size = RangedFileReader.block_size
        RangedFileReader.block_size = 3

        content = open(path.join(media_dir, "file.txt")).read()
        # specify the range header, the expected response content, and the
        # values of the content-range header byte positions
        ranges = {
            "bytes=0-10": (content[0:11], (0, 10)),
            "bytes=9-9": (content[9:10], (9, 9)),
            "bytes=-5": (content[len(content)-5:], (len(content)-5, len(content)-1)),
            "bytes=3-": (content[3:], (3, len(content)-1)),
            "bytes=-%d" % (len(content) + 1): (content, (0, len(content)-1)),
        }
        for range_, (expected_result, byte_positions) in ranges.items():
            response = self.client.get('/%s/%s' % (self.prefix, "file.txt"), HTTP_RANGE=range_)
            self.assertEqual(expected_result, b''.join(response))
            self.assertEqual(int(response['Content-Length']), len(expected_result))
            self.assertEqual(response['Content-Range'], "bytes %d-%d/%d" % (byte_positions + (len(content),)))

        RangedFileReader.block_size = original_block_size

class StaticHelperTest(StaticTests):
    """
    Test case to make sure the static URL pattern helper works as expected
    """
    def setUp(self):
        super(StaticHelperTest, self).setUp()
        self._old_views_urlpatterns = urls.urlpatterns[:]
        urls.urlpatterns += static('/media/', document_root=media_dir)

    def tearDown(self):
        super(StaticHelperTest, self).tearDown()
        urls.urlpatterns = self._old_views_urlpatterns


class StaticUtilsTests(unittest.TestCase):
    def test_was_modified_since_fp(self):
        """
        Test that a floating point mtime does not disturb was_modified_since.
        (#18675)
        """
        mtime = 1343416141.107817
        header = http_date(mtime)
        self.assertFalse(was_modified_since(header, mtime))
