#!/usr/bin/env python

import os,generate,json
import generate


# basic tests for quality, not some kind of guarantee that it
# works.  Run generate.py at least once successfully before
# you try this, it will load up the cache

#http://www.loc.gov/marc/bibliographic/concise/bd264.html
#_marc_bibliographic_concise_bd264.html

class FakeCacher(object):
	def fetch_text(self,url):
		return open(os.path.join(".cache","_marc_bibliographic_concise_bd264.html")).read()

c = generate.Crawler(FakeCacher())
tag, data = c.get_field_data("whateva")

assert '264' == tag, "test file contained unexpected tag %s" % tag
assert 'indicators' in data, "264 tag didn't contain indicators"
assert 'subfields' in data, "264 tag didn't contain subfields"
assert len(data['subfields']) ==  6, "Unexpected # of subfields (%d)" % len(data['subfields'])

c = generate.Crawler()
d = c.as_dict()
for tag, data in d.iteritems():
    if data['control_field']:
        assert 'indicators' not in data, "Control field %s contained indicators" % tag
        assert 'subfields' not in data, "Control field %s contained subfields"%tag
    else:
        assert 'indicators' in data, "Field %s had no indicators" % tag
        assert 'subfields' in data, "Field %s had no subfields" % tag
        for sf, d in data['subfields'].iteritems():
            assert 'repeatable' in d
            assert 'definition' in d




