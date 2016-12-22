# -*- coding: utf-8 -*-
from logging import getLogger
from pkg_resources import get_distribution
from openprocurement.api.utils import (
    error_handler,
    _apply_patch
)


PKG = get_distribution(__package__)
LOGGER = getLogger(PKG.project_name)
HEADER = 'X-Revision-N'


def extract_doc(request, _id, doc_type):
    doc = request.registry.db.get(_id)
    if doc is None or doc.get('doc_type') != doc_type:
        request.errors.add('url', '{}_id'.format(doc_type.lower()), 'Not Found')
        request.errors.status = 404
        raise error_handler(request.errors)
    return doc


def extract_header(request, header=HEADER):
    request_version = request.headers.get(header, False)
    return int(request_version) if request_version and request_version.isdigit() else False


def add_header(request, value, header=''):
    if not isinstance(value, str):
        value = str(value)
    if not header:
        header = HEADER
    request.response.headerlist.append((header, value))


def apply_while(doc, revisions, rev_hash):
    for patch in reversed(revisions[1:]):
        doc = _apply_patch(doc, patch['changes'])
        if patch['rev'] == rev_hash: 
           return doc
    return ''


def includeme(config):
    config.add_request_method(extract_header)
    config.add_request_method(add_header)
