# MediaGoblin plugin for embedding RDF metadata as RDFa
#
# Copyright 2013 Commons Machinery http://commonsmachinery.se/
#
# Authors: Artem Popov <artfwo@commonsmachinery.se>
#
# Distributed under GNU Affero GPL v3, please see LICENSE in the top dir.


import os
import logging
from xml.dom import minidom

from RDFMetadata import parser
from RDFMetadata import model
from RDFMetadata import vocab

from mediagoblin.tools import pluginapi
from mediagoblin import mg_globals as mgg


_log = logging.getLogger(__name__)

PLUGIN_DIR = os.path.dirname(__file__)


def setup_plugin():
    config = pluginapi.get_config('mediagoblin_rdfa')

    pluginapi.register_template_path(os.path.join(PLUGIN_DIR, 'templates'))
    pluginapi.register_template_hooks(
        {"image_sideinfo": "mediagoblin/plugins/rdfa/metadata.html"})


license_labels = {
    "http://creativecommons.org/licenses/by/3.0/": "CC BY 3.0",
    "http://creativecommons.org/licenses/by-nc/3.0/": "CC BY-NC 3.0",
    "http://creativecommons.org/licenses/by-nc-nd/3.0/": "CC BY-NC-ND 3.0",
    "http://creativecommons.org/licenses/by-nc-sa/3.0/": "CC BY-NC-SA 3.0",
    "http://creativecommons.org/licenses/by-nd/3.0/": "CC BY-ND 3.0",
    "http://creativecommons.org/licenses/by-sa/3.0/": "CC BY-SA 3.0",
}

class ResourceProperty(object):
    """
    RDFa property.
    """
    def __init__(self, uri, label=None, content=None, resource=None, rel=None):
        self.uri = uri
        self.label = label
        self.content = content
        self.resource = resource
        self.rel = rel

    def __str__(self):
        return "%s, %s, %s, %s, %s" % (self.uri, self.label, self.content, self.resource, self.rel)


class ResourceProperties(object):
    """
    RDFa representation of a metadata resource.
    
    Attributes:
        header_properties: list of properties, that typically come first
                           when displaying the metadata.
        tech_properties: list of properties, that should be hidden
                         from the user.
    """
    header_properties = [
        # title synonyms
        vocab.dc.title.uri,
        vocab.dcterms.title.uri,
        # attribution synonyms
        vocab.cc.attributionURL.uri,
        vocab.cc.attributionName.uri,
        # license synonyms
        vocab.dcterms.license.uri,
        vocab.cc.license.uri,
        vocab.xhtml.license.uri,
    ]

    tech_properties = [term.uri for term in [
        # type synonyms
        vocab.rdf.type,
        vocab.dc.type,
        vocab.dcterms.type,
        # format synonyms
        vocab.dc.format,
        vocab.dcterms.format,
    ]]

    def __init__(self, res):
        self.properties = []
        for pred in res.predicates:
            # don't count structured properties at this stage
            if isinstance(pred.object, model.BlankNode):
                continue
            
            uri = str(pred.uri)

            try:
                label = vocab.get_term(pred.uri.ns_uri, pred.uri.local_name).label
            except LookupError:
                _log.debug("Couldn't find a vocab Term for URI %s" % uri)
                label = None
            
            if isinstance(pred.object, model.LiteralNode):
                content = str(pred.object.value)
            else:
                content = None

            if isinstance(pred.object, model.ResourceNode):
                resource = str(pred.object.uri)
            else:
                resource = None

            p = ResourceProperty(uri=uri, label=label, content=content, resource=resource)
            self.properties.append(p)

        self.title = None
        if self.find_property(vocab.dc.title.uri):
            self.title = self.find_property(vocab.dc.title.uri)
        elif self.find_property(vocab.dcterms.title.uri):
            self.title = self.find_property(vocab.dcterms.title.uri)

        self.attribution = None
        if self.find_property(vocab.cc.attributionURL.uri) and \
           self.find_property(vocab.cc.attributionName.uri):
            url = self.find_property(vocab.cc.attributionURL.uri)
            name = self.find_property(vocab.cc.attributionName.uri)
            self.attribution = ResourceProperty(uri=vocab.cc.attributionName.uri,
                label=vocab.cc.Attribution.label,
                content=name.content,
                resource=url.resource,
                rel=vocab.cc.attributionURL.uri)

        self.license = None
        if self.find_property(vocab.dcterms.license.uri):
            self.license = self.find_property(vocab.dcterms.license.uri)
        elif self.find_property(vocab.cc.license.uri):
            self.license = self.find_property(vocab.cc.license.uri)
        elif self.find_property(vocab.xhtml.license.uri):
            self.license = self.find_property(vocab.xhtml.license.uri)

        if self.license and not self.license.content:
            self.license.content = license_labels.get(self.license.resource, None)
        
        # FIXME: attributionURL is currently used for about="" attributes, is that okay?
        self.attributionURL = self.find_property(vocab.cc.attributionURL.uri)
        #if not self.attributionURL and res.uri:
        #    self.attributionURL = str(res.uri)
    
    def find_property(self, uri):
        for p in self.properties:
            if uri == p.uri:
                return p
        return None

    def get_display_properties(self):
        properties = []
        if self.title:
            properties.append(self.title)
        if self.attribution:
            properties.append(self.attribution)
        else:
            # in case we have either an attributionURL
            # or an attributionName, append either
            if self.find_property(vocab.cc.attributionURL.uri):
                properties.append(self.find_property(vocab.cc.attributionURL.uri))
            if self.find_property(vocab.cc.attributionName.uri):
                properties.append(self.find_property(vocab.cc.attributionName.uri))
        if self.license:
            properties.append(self.license)
        
        for p in self.properties:
            if p.uri not in ResourceProperties.header_properties and \
               p.uri not in ResourceProperties.tech_properties:
                properties.append(p)

        return properties

    def get_tech_properties(self):
        properties = []

        for p in self.properties:
            if p.uri in ResourceProperties.tech_properties:
                properties.append(p)

        return properties

def rdf_properties(doc):
    rdfs = doc.getElementsByTagNameNS("http://www.w3.org/1999/02/22-rdf-syntax-ns#", 'RDF')

    if not rdfs:
        return None

    rdfas = []
    # collect rdf elements, that have an attributionURL, always picking the 1st element from the 1st node
    for i, rdf in enumerate(rdfs):
        root = parser.parse_RDFXML(doc = doc, root_element = rdf)

        for j, res in enumerate(root.itervalues()):
            if i == 0 and j == 0:
                rdfas.append(ResourceProperties(res))
            else:
                properties = ResourceProperties(res)
                if properties.attributionURL is not None:
                    rdfas.append(properties)

    return rdfas


def add_remix_to_context(context):
    entry = context['media']
    filename = mgg.app.public_store.get_local_path(entry.media_files['original'])
    doc = minidom.parse(filename)

    works = rdf_properties(doc)
    if works:
        context['work_metadata'] = works[0]
        if works[1:]:
            context['source_metadata'] = works[1:]

    return context

hooks = {
    'setup': setup_plugin,
    ('mediagoblin.user_pages.media_home',
     'mediagoblin/media_displays/svg.html'): add_remix_to_context,
}
