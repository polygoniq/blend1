#!/usr/bin/python3
# copyright (c) 2018- polygoniq xyz s.r.o.

import bpy
import mathutils
import numpy
import unittest
import math
import typing
import itertools


class AlignedBox:
    """Axis-aligned bounding box
    """

    def __init__(
        self,
        min: typing.Optional[mathutils.Vector] = None,
        max: typing.Optional[mathutils.Vector] = None
    ):
        self.min = min if min is not None else mathutils.Vector((math.inf,) * 3)
        self.max = max if max is not None else mathutils.Vector((-math.inf,) * 3)

    def is_valid(self) -> bool:
        """Checks whether this aligned box is valid

        Aligned box is valid if and only if its volume is non-negative,
        any aligned box becomes valid if it was extended by at least one point or any other object
        """
        for min_field, max_field in zip(self.min, self.max):
            if min_field > max_field:
                return False
        return True

    def extend_by_point(self, point: mathutils.Vector) -> None:
        """Extends this aligned box by given infinitesimal point

        This makes sure the resulting aligned box contains everything it contained before, plus
        the given point.
        """
        self.min.x = min(self.min.x, point.x)
        self.min.y = min(self.min.y, point.y)
        self.min.z = min(self.min.z, point.z)

        self.max.x = max(self.max.x, point.x)
        self.max.y = max(self.max.y, point.y)
        self.max.z = max(self.max.z, point.z)

    def extend_by_object(
        self,
        obj: bpy.types.Object,
        parent_collection_matrix: mathutils.Matrix = mathutils.Matrix.Identity(4)
    ) -> None:
        """Extend the bounding box to cover given object

        If the AlignedBox is extended by object then min_x, max_x,... values are in world space,
        not object local space. When object moves after initialization of the AlignedBox,
        coordinate properties are not recomputed to match new object's position - this class does
        not store any reference to initialization objects.
        AlignedBox computes boundaries even for instanced collection objects, that's its main
        difference compared to the bound_box property of bpy.types.Object.

        Note: Other methods of this class are space-neutral but this method only makes sense if
        the bounding box is considered a world-space bounding box.
        """
        # matrix_world is matrix relative to object's blend.
        # Thus collection objects have offset inside collection defined by their matrix_world.
        # We need to multiply parent_collection_matrix by obj.matrix_world in recursion
        # to get matrix relevant to top-most collection world space.
        obj_matrix = parent_collection_matrix @ obj.matrix_world
        # if object is a collection, it has bounding box ((0,0,0), (0,0,0), ...)
        # we need to manually traverse objects from collections and extend main bounding box
        # to contain all objects
        if obj.instance_type == 'COLLECTION':
            collection = obj.instance_collection
            if collection is not None:  # if this happens we assume no objects
                for collection_obj in collection.objects:
                    self.extend_by_object(collection_obj, obj_matrix)
        else:
            for corner in obj.bound_box:
                self.extend_by_point(obj_matrix @ mathutils.Vector(corner))

    def get_eccentricity(self) -> mathutils.Vector:
        """Returns relative eccentricity in each axis.
        """
        return (self.max - self.min) / 2.0

    def get_center(self) -> mathutils.Vector:
        return (self.min + self.max) / 2.0

    def get_size(self) -> mathutils.Vector:
        return self.max - self.min

    def get_corners(self) -> typing.Iterable[mathutils.Vector]:
        for i, j, k in itertools.product([self.min, self.max], repeat=3):
            yield mathutils.Vector((i.x, j.y, k.z))

    def __str__(self):
        return (
            f"Aligned Box\n"
            f"X = ({self.min.x}, {self.max.x})\n"
            f"Y = ({self.min.y}, {self.max.y})\n"
            f"Z = ({self.min.z}, {self.max.z})"
        )


def plane_from_points(points):
    assert len(points) == 3
    p1, p2, p3 = points

    v1 = p3 - p1
    v2 = p2 - p1

    normal = numpy.cross(v1, v2)
    normal_magnitude = numpy.linalg.norm(normal)
    normal /= normal_magnitude
    offset = numpy.dot(normal, p3)
    centroid = numpy.sum(points, 0) / len(points)

    return (normal, offset, centroid)


def fit_plane_to_points(points):
    assert len(points) >= 3
    return plane_from_points(points[:3])

    # TODO: This is borked :-(
    centroid = numpy.sum(points, 0) / len(points)
    centered_points = points - centroid
    svd = numpy.linalg.svd(numpy.transpose(centered_points))
    plane_normal = svd[0][2]
    # now that we have the normal let's fit the centroid to the plane to find the offset
    offset = numpy.dot(plane_normal, centroid)
    return (plane_normal, offset, centroid)


class PlaneFittingTest(unittest.TestCase):
    def test_3pts(self):
        # unit plane - (0, 0, 1), 0
        normal, offset, _ = fit_plane_to_points([(1, -1, 0), (-1, 0, 0), (0, 1, 0)])
        self.assertAlmostEqual(normal[0], 0)
        self.assertAlmostEqual(normal[1], 0)
        self.assertAlmostEqual(normal[2], 1)
        self.assertAlmostEqual(offset, 0)

        normal, offset, _ = fit_plane_to_points([(2, -2, 0), (-1, 0, 0), (0, 1, 0)])
        self.assertAlmostEqual(normal[0], 0)
        self.assertAlmostEqual(normal[1], 0)
        self.assertAlmostEqual(normal[2], 1)
        self.assertAlmostEqual(offset, 0)

        # offset unit plane - (0, 0, 1), 1
        normal, offset, _ = fit_plane_to_points([(2, -2, 1), (-1, 0, 1), (0, 1, 1)])
        self.assertAlmostEqual(normal[0], 0)
        self.assertAlmostEqual(normal[1], 0)
        self.assertAlmostEqual(normal[2], 1)
        self.assertAlmostEqual(offset, 1)

    def test_4pts(self):
        # unit plane - (0, 0, 1), 0
        normal, offset, _ = fit_plane_to_points([(1, -1, 0), (-1, 0, 0), (0, 1, 0), (1, 1, 0)])
        self.assertAlmostEqual(normal[0], 0)
        self.assertAlmostEqual(normal[1], 0)
        self.assertAlmostEqual(normal[2], 1)
        self.assertAlmostEqual(offset, 0)

        # can't fit precisely! unit plane - (0, 0, 1), 0
        large = 100000000000
        normal, offset, _ = fit_plane_to_points(
            [(-large, -large, 0.1), (-large, large, -0.1), (large, -large, 0.1), (large, large, -0.1)])
        self.assertAlmostEqual(normal[0], 0)
        self.assertAlmostEqual(normal[1], 0)
        self.assertAlmostEqual(normal[2], 1)
        self.assertAlmostEqual(offset, 0)


if __name__ == "__main__":
    unittest.main()
