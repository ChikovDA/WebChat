# -*- coding: utf-8 -*-
"""
Seamless Polymorphic Inheritance for Django Models
"""
from __future__ import absolute_import

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.fields.related import ReverseOneToOneDescriptor, ForwardManyToOneDescriptor
from django.db.utils import DEFAULT_DB_ALIAS
from django.utils import six

from .base import PolymorphicModelBase
from .managers import PolymorphicManager
from .query_translate import translate_polymorphic_Q_object

###################################################################################
# PolymorphicModel


class PolymorphicTypeUndefined(LookupError):
    pass


class PolymorphicTypeInvalid(RuntimeError):
    pass


class PolymorphicModel(six.with_metaclass(PolymorphicModelBase, models.Model)):
    """
    Abstract base class that provides polymorphic behaviour
    for any model directly or indirectly derived from it.

    PolymorphicModel declares one field for internal use (:attr:`polymorphic_ctype`)
    and provides a polymorphic manager as the default manager (and as 'objects').
    """

    # for PolymorphicModelBase, so it can tell which models are polymorphic and which are not (duck typing)
    polymorphic_model_marker = True

    # for PolymorphicQuery, True => an overloaded __repr__ with nicer multi-line output is used by PolymorphicQuery
    polymorphic_query_multiline_output = False

    # avoid ContentType related field accessor clash (an error emitted by model validation)
    #: The model field that stores the :class:`~django.contrib.contenttypes.models.ContentType` reference to the actual class.
    polymorphic_ctype = models.ForeignKey(
        ContentType, null=True, editable=False, on_delete=models.CASCADE,
        related_name='polymorphic_%(app_label)s.%(class)s_set+'
    )

    # some applications want to know the name of the fields that are added to its models
    polymorphic_internal_model_fields = ['polymorphic_ctype']

    # Note that Django 1.5 removes these managers because the model is abstract.
    # They are pretended to be there by the metaclass in PolymorphicModelBase.get_inherited_managers()
    objects = PolymorphicManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"

    @classmethod
    def translate_polymorphic_Q_object(cls, q):
        return translate_polymorphic_Q_object(cls, q)

    def pre_save_polymorphic(self, using=DEFAULT_DB_ALIAS):
        """
        Make sure the ``polymorphic_ctype`` value is correctly set on this model.
        """
        # This function may be called manually in special use-cases. When the object
        # is saved for the first time, we store its real class in polymorphic_ctype.
        # When the object later is retrieved by PolymorphicQuerySet, it uses this
        # field to figure out the real class of this object
        # (used by PolymorphicQuerySet._get_real_instances)
        if not self.polymorphic_ctype_id:
            self.polymorphic_ctype = ContentType.objects.db_manager(using).get_for_model(self, for_concrete_model=False)
    pre_save_polymorphic.alters_data = True

    def save(self, *args, **kwargs):
        """Calls :meth:`pre_save_polymorphic` and saves the model."""
        using = kwargs.get('using', self._state.db or DEFAULT_DB_ALIAS)
        self.pre_save_polymorphic(using=using)
        return super(PolymorphicModel, self).save(*args, **kwargs)
    save.alters_data = True

    def get_real_instance_class(self):
        """
        Return the actual model type of the object.

        If a non-polymorphic manager (like base_objects) has been used to
        retrieve objects, then the real class/type of these objects may be
        determined using this method.
        """
        if self.polymorphic_ctype_id is None:
            raise PolymorphicTypeUndefined((
                "The model {}#{} does not have a `polymorphic_ctype_id` value defined.\n"
                "If you created models outside polymorphic, e.g. through an import or migration, "
                "make sure the `polymorphic_ctype_id` field points to the ContentType ID of the model subclass."
            ).format(self.__class__.__name__, self.pk))

        # the following line would be the easiest way to do this, but it produces sql queries
        # return self.polymorphic_ctype.model_class()
        # so we use the following version, which uses the ContentType manager cache.
        # Note that model_class() can return None for stale content types;
        # when the content type record still exists but no longer refers to an existing model.
        model = ContentType.objects.db_manager(self._state.db).get_for_id(self.polymorphic_ctype_id).model_class()

        # Protect against bad imports (dumpdata without --natural) or other
        # issues missing with the ContentType models.
        if model is not None \
                and not issubclass(model, self.__class__) \
                and not issubclass(model, self.__class__._meta.proxy_for_model):
            raise PolymorphicTypeInvalid("ContentType {0} for {1} #{2} does not point to a subclass!".format(
                self.polymorphic_ctype_id, model, self.pk,
            ))
        return model

    def get_real_concrete_instance_class_id(self):
        model_class = self.get_real_instance_class()
        if model_class is None:
            return None
        return ContentType.objects.db_manager(self._state.db).get_for_model(model_class, for_concrete_model=True).pk

    def get_real_concrete_instance_class(self):
        model_class = self.get_real_instance_class()
        if model_class is None:
            return None
        return ContentType.objects.db_manager(self._state.db).get_for_model(model_class, for_concrete_model=True).model_class()

    def get_real_instance(self):
        """
        Upcast an object to it's actual type.

        If a non-polymorphic manager (like base_objects) has been used to
        retrieve objects, then the complete object with it's real class/type
        and all fields may be retrieved with this method.

        .. note::
            Each method call executes one db query (if necessary).
            Use the :meth:`~polymorphic.managers.PolymorphicQuerySet.get_real_instances`
            to upcast a complete list in a single efficient query.
        """
        real_model = self.get_real_instance_class()
        if real_model == self.__class__:
            return self
        return real_model.objects.db_manager(self._state.db).get(pk=self.pk)

    def __init__(self, * args, ** kwargs):
        """Replace Django's inheritance accessor member functions for our model
        (self.__class__) with our own versions.
        We monkey patch them until a patch can be added to Django
        (which would probably be very small and make all of this obsolete).

        If we have inheritance of the form ModelA -> ModelB ->ModelC then
        Django creates accessors like this:
        - ModelA: modelb
        - ModelB: modela_ptr, modelb, modelc
        - ModelC: modela_ptr, modelb, modelb_ptr, modelc

        These accessors allow Django (and everyone else) to travel up and down
        the inheritance tree for the db object at hand.

        The original Django accessors use our polymorphic manager.
        But they should not. So we replace them with our own accessors that use
        our appropriate base_objects manager.
        """
        super(PolymorphicModel, self).__init__(*args, ** kwargs)

        if self.__class__.polymorphic_super_sub_accessors_replaced:
            return
        self.__class__.polymorphic_super_sub_accessors_replaced = True

        def create_accessor_function_for_model(model, accessor_name):
            def accessor_function(self):
                attr = model._base_objects.get(pk=self.pk)
                return attr
            return accessor_function

        subclasses_and_superclasses_accessors = self._get_inheritance_relation_fields_and_models()

        for name, model in subclasses_and_superclasses_accessors.items():
            # Here be dragons.
            orig_accessor = getattr(self.__class__, name, None)
            if issubclass(type(orig_accessor), (ReverseOneToOneDescriptor, ForwardManyToOneDescriptor)):
                setattr(self.__class__, name, property(create_accessor_function_for_model(model, name)))

    def _get_inheritance_relation_fields_and_models(self):
        """helper function for __init__:
        determine names of all Django inheritance accessor member functions for type(self)"""

        def add_model(model, field_name, result):
            result[field_name] = model

        def add_model_if_regular(model, field_name, result):
            if (issubclass(model, models.Model)
                    and model != models.Model
                    and model != self.__class__
                    and model != PolymorphicModel):
                add_model(model, field_name, result)

        def add_all_super_models(model, result):
            for super_cls, field_to_super in model._meta.parents.items():
                if field_to_super is not None:  # if not a link to a proxy model
                    field_name = field_to_super.name  # the field on model can have a different name to super_cls._meta.module_name, if the field is created manually using 'parent_link'
                    add_model_if_regular(super_cls, field_name, result)
                    add_all_super_models(super_cls, result)

        def add_all_sub_models(super_cls, result):
            for sub_cls in super_cls.__subclasses__():  # go through all subclasses of model
                if super_cls in sub_cls._meta.parents:  # super_cls may not be in sub_cls._meta.parents if super_cls is a proxy model
                    field_to_super = sub_cls._meta.parents[super_cls]  # get the field that links sub_cls to super_cls
                    if field_to_super is not None:    # if filed_to_super is not a link to a proxy model
                        super_to_sub_related_field = field_to_super.remote_field
                        if super_to_sub_related_field.related_name is None:
                            # if related name is None the related field is the name of the subclass
                            to_subclass_fieldname = sub_cls.__name__.lower()
                        else:
                            # otherwise use the given related name
                            to_subclass_fieldname = super_to_sub_related_field.related_name

                        add_model_if_regular(sub_cls, to_subclass_fieldname, result)

        result = {}
        add_all_super_models(self.__class__, result)
        add_all_sub_models(self.__class__, result)
        return result
