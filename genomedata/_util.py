#!/usr/bin/env python

from __future__ import absolute_import, division, print_function

# Copyright 2008-2014 Michael M. Hoffman <michael.hoffman@utoronto.ca>

from contextlib import closing
from gzip import open as _gzip_open
from os import extsep
import struct
import sys

from numpy import array, empty
from tables import Filters

BIG_WIG_FIELD_COUNT = 4
BIG_WIG_SIGNATURE = 0x888FFC26
BIG_WIG_SIGNATURE_BYTE_SIZE = 4

FILTERS_GZIP = Filters(complevel=1)

EXT_GZ = "gz"
SUFFIX_GZ = extsep + EXT_GZ

def die(msg="Unexpected error."):
    print(msg, file=sys.stderr)
    sys.exit(1)

class LightIterator(object):
    def __init__(self, handle):
        self._handle = handle
        self._defline = None

    def __iter__(self):
        return self

    def next(self):
        lines = []
        defline_old = self._defline

        for line in self._handle:
            if not line:
                if not defline_old and not lines:
                    raise StopIteration
                if defline_old:
                    self._defline = None
                    break
            elif line.startswith(">"):
                self._defline = line[1:].rstrip()
                if defline_old or lines:
                    break
                else:
                    defline_old = self._defline
            else:
                lines.append(line.rstrip())

        if not lines:
            raise StopIteration

        if defline_old is None:
            raise ValueError("no definition line found at next position in %r" % self._handle)

        return defline_old, ''.join(lines)

# XXX: suggest as default
def fill_array(scalar, shape, dtype=None, *args, **kwargs):
    if dtype is None:
        dtype = array(scalar).dtype

    res = empty(shape, dtype, *args, **kwargs)
    res.fill(scalar)

    return res

# XXX: suggest as default
def gzip_open(*args, **kwargs):
    return closing(_gzip_open(*args, **kwargs))

def maybe_gzip_open(filename, *args, **kwargs):
    if filename.endswith(SUFFIX_GZ):
        return gzip_open(filename, *args, **kwargs)
    else:
        return open(filename, *args, **kwargs)

def init_num_obs(num_obs, continuous):
    curr_num_obs = continuous.shape[1]
    assert num_obs is None or num_obs == curr_num_obs

    return curr_num_obs

def new_extrema(func, data, extrema):
    curr_extrema = func(data, 0)

    return func([extrema, curr_extrema], 0)


def is_big_wig(filename):
    """ Checks that the given filename refers to a valid bigWig file """
    with open(filename, "rb") as big_wig_file:
        signature_string = big_wig_file.read(BIG_WIG_SIGNATURE_BYTE_SIZE)

    # unpack returns a tuple regardless of length
    # the kent reference checks both little endian and big endian packing
    # of the 4 byte signature
    little_endian_signature = struct.unpack("<L", signature_string)[0]
    big_endian_signature = struct.unpack(">L", signature_string)[0]

    if (little_endian_signature == BIG_WIG_SIGNATURE or
       big_endian_signature == BIG_WIG_SIGNATURE):
        return True

    return False


def ignore_comments(iterable):
    return (item for item in iterable if not item.startswith("#"))


def main(args=sys.argv[1:]):
    pass

if __name__ == "__main__":
    sys.exit(main())
