import jinja2
import os
import textwrap
from datetime import datetime
from collections import OrderedDict


from . import trait_extractors as tx
from . import utils, __version__


FILE_HEADER = """# -*- coding: {{encoding}} -*-
# Auto-generated by schemapi: do not modify file directly
# - schemapi version: {{version}}
# - date:    {{ date }}
"""


OBJECT_TEMPLATE = '''
{% for import in cls.basic_imports %}
{{ import }}
{%- endfor %}


def _localname(name):
    """Construct an object name relative to the local module"""
    return "{0}.{1}".format(__name__, name)

{% for cls in classes %}
{{ cls.object_code() }}
{% endfor %}
'''


class JSONSchemaTraitlets(object):
    """A class to wrap JSON Schema objects and reason about their contents

    Parameters
    ----------
    schemaobj : JSONSchema object
        The JSONSchema object for which to build the interface
    """
    object_template = OBJECT_TEMPLATE
    file_header = FILE_HEADER
    __draft__ = 4

    attr_defaults = {'title': '',
                     'description': '',
                     'properties': {},
                     'definitions': {},
                     'default': None,
                     'examples': {},
                     'type': 'object',
                     'required': [],
                     'additionalProperties': True}
    basic_imports = ["import traitlets as T",
                     "from . import jstraitlets as jst"]

    # an ordered list of trait extractor classes.
    # these will be checked in-order, and return a trait_code when
    # a match is found.
    trait_extractors = [tx.AnyOfObject, tx.OneOfObject, tx.AllOfObject,
                        tx.RefObject, tx.RefTrait,
                        tx.Not, tx.AnyOf, tx.AllOf, tx.OneOf,
                        tx.NamedEnum, tx.Enum,
                        tx.SimpleType, tx.CompoundType,
                        tx.Array, tx.EmptySchema, tx.Object]

    def __init__(self, schemaobj):
        self.schemaobj = schemaobj
        self.schema = schemaobj.schema
        self.plugins = []
        self._trait_extractor = None

    def add_plugins(self, *plugins):
        self.plugins.extend(list(plugins))

    @property
    def all_definitions(self):
        return OrderedDict(sorted(self.schemaobj.definitions.items()))

    @property
    def trait_extractor(self):
        if self._trait_extractor is None:
            # TODO: handle multiple matches with an AllOf()
            for TraitExtractor in self.trait_extractors:
                trait_extractor = TraitExtractor(self)
                if trait_extractor.check():
                    self._trait_extractor = trait_extractor
                    break
            else:
                raise ValueError("No recognized trait code for schema with "
                                 "keys {0}".format(tuple(self.schema.keys())))
        return self._trait_extractor

    def indented_description(self, indent_level=2):
        return utils.format_description(self.description,
                                        indent=4 * indent_level)

    def initialize_child(self, schema, name=None):
        """
        Make a child instance, appropriately defining the parent and root
        """
        return self.__class__(self.schemaobj.initialize_child(schema, name=name))

    def __getitem__(self, key):
        return self.schema[key]

    def __contains__(self, key):
        return key in self.schema

    def __getattr__(self, attr):
        if attr in self.attr_defaults:
            return self.schema.get(attr, self.attr_defaults[attr])
        raise AttributeError("'{0}' object has no attribute '{1}'"
                             "".format(self.__class__.__name__, attr))

    def get(self, *args):
        return self.schema.get(*args)

    @property
    def is_root(self):
        return self.schemaobj.root is self.schemaobj

    @property
    def is_trait(self):
        if 'properties' in self:
            return False
        elif self.type != 'object':
            return True
        elif 'enum' in self:
            return True
        elif '$ref' in self:
            return self.wrapped_ref().is_trait
        elif 'anyOf' in self:
            return any(self.initialize_child(spec).is_trait
                       for spec in self['anyOf'])
        elif 'allOf' in self:
            return any(self.initialize_child(spec).is_trait
                       for spec in self['allOf'])
        elif 'oneOf' in self:
            return any(self.initialize_child(spec).is_trait
                       for spec in self['oneOf'])
        else:
            return False

    @property
    def is_object(self):
        if 'properties' in self:
            return True
        elif '$ref' in self:
            return self.wrapped_ref().is_object
        elif 'anyOf' in self:
            return all(self.initialize_child(spec).is_object
                       for spec in self['anyOf'])
        elif 'allOf' in self:
            return all(self.initialize_child(spec).is_object
                       for spec in self['allOf'])
        elif 'oneOf' in self:
            return all(self.initialize_child(spec).is_object
                       for spec in self['oneOf'])
        else:
            return False

    @property
    def is_reference(self):
        return '$ref' in self.schema

    @property
    def is_named_object(self):
        try:
            return bool(self.classname)
        except NotImplementedError:
            return False

    @property
    def type_description(self):
        return self.trait_extractor.type_description()

    @property
    def classname(self):
        if self.name:
            return utils.regularize_name(self.name)
        elif self.is_root:
            return self.root_name
        elif self.is_reference:
            return self.wrapped_ref().classname
        else:
            raise NotImplementedError("class name for schema with keys "
                                      "{0}".format(tuple(self.schema.keys())))

    @property
    def name(self):
        return self.schemaobj.name

    @property
    def root_name(self):
        return self.schemaobj.root_name

    @property
    def root(self):
        return self.schemaobj.root

    @property
    def full_classname(self):
        return "_localname('{0}')".format(self.classname)

    @property
    def schema_hash(self):
        return utils.hash_schema(self.schema)

    @property
    def modulename(self):
        return 'schema'

    @property
    def filename(self):
        return self.modulename + '.py'

    @property
    def baseclass(self):
        return "jst.JSONHasTraits"

    @property
    def additional_traits(self):
        if self.additionalProperties in [True, False]:
            return repr(self.additionalProperties)
        else:
            trait = self.initialize_child(self.additionalProperties)
            return "[{0}]".format(trait.trait_code)

    @property
    def trait_map(self):
        return utils.trait_name_map(sorted(self.properties.keys()))

    @property
    def import_statement(self):
        return self.trait_extractor.import_statement()

    def wrapped_definitions(self):
        """Return definition dictionary wrapped as JSONSchema objects"""
        return OrderedDict((name.lower(), self.initialize_child(schema, name=name))
                           for name, schema in
                           sorted(self.all_definitions.items()))

    def wrapped_properties(self):
        """Return property dictionary wrapped as JSONSchema objects"""
        reverse_map = {v:k for k, v in self.trait_map.items()}
        return OrderedDict((reverse_map.get(name, name), self.initialize_child(val))
                           for name, val in sorted(self.properties.items()))

    def wrapped_ref(self):
        return self.get_reference(self.schema['$ref'])

    def get_reference(self, ref):
        """
        Get the JSONSchema object for the given reference code.

        Reference codes should look something like "#/definitions/MyDefinition"
        """
        if not ref:
            raise ValueError("empty reference")

        path = ref.split('/')
        name = path[-1]
        if path[0] != '#':
            raise ValueError("Unrecognized $ref format: '{0}'".format(ref))
        elif len(path) == 1 or path[1] == '':
            return self.__class__(self.root)
        try:
            schema = self.root.schema
            for key in path[1:]:
                schema = schema[key]
        except KeyError:
            raise ValueError("$ref='{0}' not present in the schema".format(ref))

        return self.initialize_child(schema, name=name)

    @property
    def trait_code(self):
        """Create the trait code for the given schema"""
        kwargs = {}
        if self.description:
            kwargs['help'] = textwrap.shorten(self.description, 70)

        # TODO: handle multiple matches with an AllOf()
        for TraitExtractor in self.trait_extractors:
            trait_extractor = TraitExtractor(self)
            if trait_extractor.check():
                return trait_extractor.trait_code(**kwargs)
        else:
            raise ValueError("No recognized trait code for schema with "
                             "keys {0}".format(tuple(self.schema.keys())))

    def object_code(self):
        """Return code to define an object for this schema"""
        # TODO: handle multiple matches with an AllOf()
        for TraitExtractor in self.trait_extractors:
            trait_extractor = TraitExtractor(self)
            if trait_extractor.check():
                return trait_extractor.object_code()
        else:
            raise ValueError("No recognized object code for schema with "
                             "keys {0}".format(tuple(self.schema.keys())))

    @property
    def trait_imports(self):
        """Return the list of imports required in the trait_code definition"""
        # TODO: handle multiple matches with an AllOf()
        for TraitExtractor in self.trait_extractors:
            trait_extractor = TraitExtractor(self)
            if trait_extractor.check():
                return trait_extractor.trait_imports()
        else:
            raise ValueError("No recognized trait code for schema with "
                             "keys {0}".format(tuple(self.schema.keys())))

    @property
    def object_imports(self):
        """Return the list of imports required in the object_code definition"""
        imports = list(self.basic_imports)
        if isinstance(self.additionalProperties, dict):
            default = self.initialize_child(self.additionalProperties)
            imports.extend(default.trait_imports)
        if self.is_reference:
            imports.append(self.wrapped_ref().import_statement)
        for trait in self.wrapped_properties().values():
            imports.extend(trait.trait_imports)
        return sorted(set(imports), reverse=True)

    @property
    def module_imports(self):
        """List of imports of all definitions for the root module"""
        imports = [self.import_statement]

        # Add imports for all defined objects
        defn_imports = []
        for obj in self.wrapped_definitions().values():
            defn_imports.append(obj.import_statement)
        imports.extend(sorted(defn_imports))

        # Add imports from plugins
        for plugin in self.plugins:
            imports.extend(sorted(plugin.module_imports(self)))
        return imports

    def source_tree(self, encoding='utf-8'):
        """Return the JSON specification of the module source tree

        This can be passed to ``schemapi.utils.load_dynamic_module``
        or to ``schemapi.utils.save_module``

        See also the ``write_module()`` and ``load_module()`` methods.
        """
        assert self.is_root

        template = jinja2.Template(self.object_template)
        header = jinja2.Template(self.file_header)

        classes = [self]

        # Determine list of classes to generate
        classes += [schema for schema in self.wrapped_definitions().values()]
        classes = sorted(classes, key=lambda obj: (obj.trait_extractor.priority, obj.classname))
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        header_content = header.render(date=date,
                                       version=__version__,
                                       encoding=encoding)
        schema_content = template.render(cls=self, classes=classes)

        def localfile(path):
            return os.path.join(os.path.dirname(__file__), path)

        jstraitlets_content = open(localfile('src/jstraitlets.py')).read()
        test_content = open(localfile('src/tests/test_jstraitlets.py')).read()
        init_content = '\n'.join(self.module_imports)

        def add_header(content):
            return '{0}\n\n{1}'.format(header_content, content)

        tree = {
            'jstraitlets.py': add_header(jstraitlets_content),
            self.filename: add_header(schema_content),
            '__init__.py': add_header(init_content),
            'tests': {
                '__init__.py': add_header(""),
                'test_jstraitlets.py': add_header(test_content),
            }
        }
        for plugin in self.plugins:
            tree.update(plugin.code_files(self))
        return tree

    def write_module(self, modulename, location=None, quiet=True):
        """Write the module to disk

        Parameters
        ----------
        modulename : string
            The name of the module to create on disk
        location : string (optional)
            The path at which to save the module. The default is the current
            working directory.
        quiet : boolean (optional, default=True)
            if True, then silence printed output.

        Returns
        -------
        module_path : string
            The path to the resulting module

        Notes
        -----
        if you specify modulename='modulename' and location='/path/to/dir/',
        the module will be created at '/path/to/dir/modulename'.
        If this directory already exists, an error will be raised.
        """
        if location is None:
            location = os.path.abspath(os.getcwd())
        if not quiet:
            print("saving to {0} at {1}".format(modulename, location))
        return utils.save_module(spec=self.source_tree(),
                                 name=modulename,
                                 location=location,
                                 quiet=quiet)

    def load_module(self, modulename, reload_module=False):
        """Dynamically load the module into memory

        Parameters
        ----------
        modulename : string
            The name of the module to create on disk
        reload_module : boolean
            If True, then remove any previous version of the package

        Returns
        -------
        mod : ModuleType
            The dynamically loaded module
        """
        return utils.load_dynamic_module(name=modulename,
                                         specification=self.source_tree(),
                                         reload_module=reload_module)


class JSONSchemaPlugin(object):
    """Abstract base class for JSONSchema plugins.

    Plugins can be used to add additional outputs to the schema wrapper
    """
    def module_imports(self, schema):
        """Return a list of top-level imports to add at the module level"""
        raise NotImplementedError()

    def code_files(self, schema):
        """
        Return a dictionary of {filename: content} pairs
        that will be added to the module
        """
        raise NotImplementedError()
