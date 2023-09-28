#!/usr/bin/python3
# copyright (c) 2018- polygoniq xyz s.r.o.

import bpy
import typing
import time
import logging


def logged_operator(cls: typing.Type[bpy.types.Operator]):
    assert issubclass(
        cls, bpy.types.Operator), "logged_operator only accepts classes inheriting bpy.types.Operator"

    logger = logging.getLogger(f"polygoniq.{cls.__module__}")

    if hasattr(cls, "draw"):
        cls._original_draw = cls.draw

        def new_draw(self, context: bpy.types.Context):
            try:
                return cls._original_draw(self, context)
            except:
                logger.exception(f"Uncaught exception raised in {cls}.draw")

        cls.draw = new_draw

    if hasattr(cls, "modal"):
        cls._original_modal = cls.modal

        def new_modal(self, context: bpy.types.Context, event: bpy.types.Event):
            try:
                return cls._original_modal(self, context, event)
            except:
                logger.exception(f"Uncaught exception raised in {cls}.modal")
                # If exception is thrown out of the modal we want to exit it. If there are possible
                # exceptions that can occur, they should be handled in the modal itself.
                return {'FINISHED'}

        cls.modal = new_modal

    if hasattr(cls, "execute"):
        cls._original_execute = cls.execute

        def new_execute(self, context: bpy.types.Context):
            logger.info(
                f"{cls.__name__} operator execute started with arguments {self.as_keywords()}")
            start_time = time.time()
            try:
                ret = cls._original_execute(self, context)
                logger.info(
                    f"{cls.__name__} operator execute finished in {time.time() - start_time:.3f} "
                    f"seconds with result {ret}"
                )
                return ret
            except:
                logger.exception(f"Uncaught exception raised in {cls}.execute")
                # We return finished even in case an error happened, that way the user will be able
                # to undo any changes the operator has made up until the error happened
                return {'FINISHED'}

        cls.execute = new_execute

    if hasattr(cls, "invoke"):
        cls._original_invoke = cls.invoke

        def new_invoke(self, context: bpy.types.Context, event: bpy.types.Event):
            logger.debug(f"{cls.__name__} operator invoke started")
            try:
                ret = cls._original_invoke(self, context, event)
                logger.debug(f"{cls.__name__} operator invoke finished")
                return ret
            except:
                logger.exception(f"Uncaught exception raised in {cls}.invoke")
                # We return finished even in case an error happened, that way the user will be able
                # to undo any changes the operator has made up until the error happened
                return {'FINISHED'}

        cls.invoke = new_invoke

    return cls


def logged_panel(cls: typing.Type[bpy.types.Panel]):
    assert issubclass(
        cls, bpy.types.Panel), "logged_panel only accepts classes inheriting bpy.types.Panel"

    logger = logging.getLogger(f"polygoniq.{cls.__module__}")

    if hasattr(cls, "draw_header"):
        cls._original_draw_header = cls.draw_header

        def new_draw_header(self, context: bpy.types.Context):
            try:
                return cls._original_draw_header(self, context)
            except:
                logger.exception(f"Uncaught exception raised in {cls}.draw_header")

        cls.draw_header = new_draw_header

    if hasattr(cls, "draw"):
        cls._original_draw = cls.draw

        def new_draw(self, context: bpy.types.Context):
            try:
                return cls._original_draw(self, context)
            except:
                logger.exception(f"Uncaught exception raised in {cls}.draw")

        cls.draw = new_draw

    return cls


def logged_preferences(cls: typing.Type[bpy.types.AddonPreferences]):
    assert issubclass(
        cls, bpy.types.AddonPreferences), "logged_preferences only accepts classes inheriting bpy.types.AddonPreferences"

    logger = logging.getLogger(f"polygoniq.{cls.__module__}")

    if hasattr(cls, "draw"):
        cls._original_draw = cls.draw

        def new_draw(self, context: bpy.types.Context):
            try:
                return cls._original_draw(self, context)
            except:
                logger.exception(f"Uncaught exception raised in {cls}.draw")

        cls.draw = new_draw

    return cls
