#!/usr/bin/env python

"""
This is a scraper for the LoC website that will parse the human
readable HTML documentation for MARC tags, and generate machine
readable (XML) documentation.

THIS IS A WORK IN PROGRESS; the HTML on the LoC pages this scrapes is 
irregular.  Most of the work needs to be done on subfield parsing.

You'll need to have python, lxml.etree, pyquery, and requests installed
before running this script.

Questions or comments welcome in #code4lib on
irc.freenode.net.

Inspired by the original by Ed Summers.
"""

import requests
from pyquery.pyquery import PyQuery
from collections import OrderedDict
from urlparse import urljoin
import hashlib
import re
import os, sys
import json

def normalize(input_string):
    return input_string and re.sub(r"\s+"," ",input_string).strip() or input_string


def two_split(input_string,delimiter='-'):
    """splits a string into at most two parts and normalizes each part"""
    return [ normalize(x) for x in input_string.split('-',1) ]


class Crawler(object):
    """Crawls the concise MARC info pages on the LoC site.
    Instances of this object are iterable, or you can call
    crawler.as_dict() to get an object you can serialize however
    you'd like.
    """

    CONTROL_FIELDS = set(('001','003', '005', '006', '007', '008'))

    # tag, name, repeatability
    field_basics_re = re.compile(r"^\s*([0-9]{3})\s*-\s*(.*)\s+\((N?R)\)$")

    subfield_re = re.compile(r"^\s*\$(.-?.?)\s+-\s+(.*)(?:\s*\((N?R)\))?$")

    def __init__(self,cacher=None):
        """
        Creates a new instance.  If no cacher is specified, builds a default instance.
        @param cacher a page caching fetcher.
        """
        if cacher is None:
            cacher = Cacher()
        self.cacher = cacher
        self.start_url = 'http://www.loc.gov/marc/bibliographic/ecbdhome.html'

    def __iter__(self):
        urls = self.get_bibliographic_urls()
        for url in urls:
            links = self.get_concise_pages(url)
            for link in links:
                td = self.get_tag_data(link)
                if td:
                    yield td

    def as_dict(self):
        """
        Gets the tag information as a dict
        """
        rv = OrderedDict()
        for tag, data  in self:
            rv[tag] = data
        return rv

    def extract_title_text(self,h1):
        m = self.field_basics_re.search(( h1.text().strip() ))
        if m:
            return m.group(1), m.group(2), m.group(3) == 'R'
        return False

    def get_tag_data(self,url):
        """
        Fetches the data from the URL and tries to extract all of the tag
        information from the page.
        
        @param url -- the URL for the *concise* tag information page.

        @return tag (string) , tag_info (dict)
                or False if information cannot be extracted from the page at url
        """
        dom = self.get_dom(url)
        tag_info = self.get_field_def(dom)
        if tag_info:
            tag, title, repeatable = tag_info
        else:
            return False
        definition = dom("div.definition")
        if not definition.size():
            definition = dom("p").eq(0)
        if not definition.size():
            definition = PyQuery("<p>Bad HTML: %s</p>" % url)
        if tag not in self.CONTROL_FIELDS:
            subfields = self.get_subfields(dom)
            if '?' in subfields: 
                raise Exception("can't parse subfields in " + url)
            try:
                indicators = self.get_indicators(dom)
            except Exception, e:
                import traceback, sys
                traceback.print_exception(*sys.exc_info())
                print e
                raise Exception("Can't get indicators from " + url, e)
        else:
            subfields = ()
            indicators = ()

        return tag, dict(title=title,definition=normalize(definition.text()),repeatable=repeatable, subfields=subfields,indicators=indicators)
        

    def get_subfields(self,dom):
        rv = OrderedDict()
        values = dom("body > div.subfieldvalue")
        def handler(idx,pel):
            pel = PyQuery(pel)
            txt = re.sub(r"\n+", " ", pel.text())
            m = self.subfield_re.match(txt)
            if m:
                sf = m.group(1).strip()
                desc = m.group(2).strip()
                if len(m.groups()) > 2:
                    repeatability = m.group(3) == 'R'
                else:
                    repeatability = None
            else:
                sys.stderr.write("<<<" + txt + ">>>")
                sf,desc,repeatability = "?", "?", False
            extra = [ x.text for x in pel("div.description") if x.text is not None ]
            rv[sf] = dict(description=desc,definition=len(extra) > 0 and normalize(" ".join(extra)) or "")
            if repeatability is not None:
                rv[sf]['repeatable'] = repeatability
            else:
                rv[sf]['range'] = True           
        values.each(handler)
        return rv

    def parse_indicator(self,dom):
        txt = dom[0].text.strip()
        definition = two_split(txt)[1]
        values = OrderedDict()
        for val in dom.eq(0)("div.indicatorvalue"):
            v,d = two_split(val.text)
            if v not in ('First','Second'):
                values[v] = d
        desc =  dom.eq(0)("div.description")
        desc = desc.size() > 0 and normalize(desc.eq(0).text()) or ""
        return dict(definition=definition,values=values,description=desc)
    
    def _indicator_dl(self,dom):
        """024 puts indicators in a nicer, but still outlier, HTML
        definition list"""
        dl = dom("div.indicators dl")
        inds = []
        values = OrderedDict()
        definition = ""
        for el in dl:
            if el.tag == 'dt':
                if values:
                    inds.append(dict(definition=definition,values=values))
                    values = OrderedDict()
                definition = el.text.split("-")[1].strip()
            elif el.tag == 'dd':
                k,v = two_split(el.text)
                values[k] = v
        if len(inds) < 2:
            inds.append(dict(definition=definition,values=values) )
        return inds

    def get_indicators(self,dom):
        tli = dom("body div.indicatorvalue")
        if tli.size() >= 2:
            first = self.parse_indicator(tli.eq(0))
            second = self.parse_indicator(tli.eq(1))
            return first,second
        else:
            return self._indicator_dl(dom)
        return ({},{})

    def get_field_def(self,dom):
        h1 = dom("h1")
        if not h1:
            sys.stderr.write("oops %s " % url)
            return url, "0", "0"        
        spans = h1("span")
        if not spans.size():
            return self.extract_title_text(h1)
        elif len(spans) == 3:
            tag, title, r = [ x.text.strip() for x in spans ]
            r = not "NR" in r
            return tag, title, r
        else:
            return self.extract_title_text(h1)

        return  url, "not found", "not found"

    def get_dom(self,url):
        dom = PyQuery(self.cacher.fetch_text(url))
        return dom.xhtml_to_html()

    def get_concise_pages(self,url):
        pq = self.get_dom(url)
        clinks = [ urljoin(url, x.get('href')) for x in pq("a") if x.text == 'Concise' ]
        return clinks


    def get_bibliographic_urls(self):
        toplinks = [ urljoin(self.start_url, x.get('href')) for x in self.get_dom(self.start_url)("a[href^=bd]") if x.get('href')[2].isdigit() ]
        return toplinks

class Cacher(object):
    """
    Simple cacher so we don't hammer the LoC website while downloading the HTML.
    If you need to expire the cache, instantiate this object with the clean kwarg set to
    True
    """
    def __init__(self, cache_dir=".cache", clean=False):
        """
        Creates a new cacher
        @param cache_dir (default: .cache) -- where to store cached files
        @param clean (default: False) -- whether to clear the cache before you start
        """
        self.cache_dir = cache_dir
        if not os.path.isdir(self.cache_dir):
            os.makedirs(self.cache_dir)
        if clean:
            for cachefile in os.listdir(self.cache_dir):
                os.unlink(os.path.join(self.cache_dir,cachefile))

    def fetch_text(self,url):
        """
        Fetches text from the cache if available, or from the network. If the
        latter, creates a file in self.cache_dir using the md5sum of the URL
        @param url -- the URL to fetch
        """           
        digest = hashlib.md5(url).hexdigest()
        pth = os.path.join(self.cache_dir, digest + ".html")
        if os.path.isfile(pth) and os.path.getsize(pth) > 0:
            with open(pth) as thefile:
                return thefile.read()
        else:
            r = requests.get(url)
            with open(pth, "w") as thefile:
                bytes = r.text        
                try:
                    output = r.text.encode('utf-8')
                    thefile.write(output)
                    return output
                except UnicodeEncodeError, u:
                    output.write(bytes)
                    return bytes


# ok start your engines
if __name__ == '__main__':
    # if you want control over the cacher, instantiate that first and
    # pass it in as a parameter to the crawler
    crawler = Crawler()    
    print json.dumps(crawler.as_dict(), indent=2)

