import re
import six

from cassandra.cluster import UserTypeDoesNotExist
from cassandra.util import OrderedDict
from cassandra.cqlengine import CQLEngineException
from cassandra.cqlengine import columns
from cassandra.cqlengine import connection
from cassandra.cqlengine import models


class UserTypeException(CQLEngineException):
    pass


class UserTypeDefinitionException(UserTypeException):
    pass


class BaseUserType(object):
    """
    The base type class; don't inherit from this, inherit from UserType, defined below
    """
    __type_name__ = None

    _fields = None
    _db_map = None

    def __init__(self, **values):
        self._values = {}

        for name, field in self._fields.items():
            value = values.get(name, None)
            if value is not None or isinstance(field, columns.BaseContainerColumn):
                value = field.to_python(value)
            value_mngr = field.value_manager(self, field, value)
            if name in values:
                value_mngr.explicit = True
            self._values[name] = value_mngr

    def __eq__(self, other):
        print self.__class__, other.__class__
        if self.__class__ != other.__class__:
            return False

        keys = set(self._fields.keys())
        other_keys = set(other._fields.keys())
        if keys != other_keys:
            return False

        for key in other_keys:
            if getattr(self, key, None) != getattr(other, key, None):
                return False

        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    @classmethod
    def register_for_keyspace(cls, keyspace):
        connection.register_udt(keyspace, cls.type_name(), cls)

    @classmethod
    def type_name(cls):
        """
        Returns the type name if it's been defined
        otherwise, it creates it from the class name
        """
        if cls.__type_name__:
            type_name = cls.__type_name__.lower()
        else:
            camelcase = re.compile(r'([a-z])([A-Z])')
            ccase = lambda s: camelcase.sub(lambda v: '{}_{}'.format(v.group(1), v.group(2)), s)

            type_name = ccase(cls.__name__)
            # trim to less than 48 characters or cassandra will complain
            type_name = type_name[-48:]
            type_name = type_name.lower()
            type_name = re.sub(r'^_+', '', type_name)
            cls.__type_name__ = type_name

        return type_name

    def validate(self):
        """
        Cleans and validates the field values
        """
        pass
        for name, field in self._fields.items():
            v = getattr(self, name)
            if v is None and not self._values[name].explicit and field.has_default:
                v = field.get_default()
            val = field.validate(v)
            setattr(self, name, val)


class UserTypeMetaClass(type):

    def __new__(cls, name, bases, attrs):
        field_dict = OrderedDict()

        field_defs = [(k, v) for k, v in attrs.items() if isinstance(v, columns.Column)]
        field_defs = sorted(field_defs, key=lambda x: x[1].position)

        # TODO: this plus more validation
        #counter_columns = [c for c in defined_columns.values() if isinstance(c, columns.Counter)]
        #if counter_columns and data_columns:
        #    raise ModelDefinitionException('counter models may not have data columns')

        def _transform_column(field_name, field_obj):
            field_dict[field_name] = field_obj
            field_obj.set_column_name(field_name)
            attrs[field_name] = models.ColumnDescriptor(field_obj)

        # transform field definitions
        for k, v in field_defs:
            # don't allow a field with the same name as a built-in attribute or method
            if k in BaseUserType.__dict__:
                raise UserTypeDefinitionException("field '{}' conflicts with built-in attribute/method".format(k))
            _transform_column(k, v)

        # create db_name -> model name map for loading
        db_map = {}
        for field_name, field in field_dict.items():
            db_map[field.db_field_name] = field_name

        attrs['_fields'] = field_dict
        attrs['_db_map'] = db_map

        klass = super(UserTypeMetaClass, cls).__new__(cls, name, bases, attrs)

        return klass


@six.add_metaclass(UserTypeMetaClass)
class UserType(BaseUserType):

    __type_name__ = None
    """
    *Optional.* Sets the name of the CQL type for this type.

    If not specified, the type name will be the name of the class, with it's module name as it's prefix.
    """
