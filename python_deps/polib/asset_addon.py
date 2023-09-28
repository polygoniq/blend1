#!/usr/bin/python3
# copyright (c) 2018- polygoniq xyz s.r.o.

import os


def is_library_blend(path: str) -> bool:
    basename = os.path.basename(path)
    # this is the new convention, two lowercase letters for prefix,
    # followed by _Library_, e.g. "mq_Library_NodeGroups.blend"
    if basename[0:2].islower() and basename[2:2 + len("_Library_")] == "_Library_":
        return True
    # old convention just started with Library_ with no prefix, e.g. Library_Botaniq_Materials.blend
    if basename.startswith("Library_"):
        return True
    return False
