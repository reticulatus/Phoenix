#---------------------------------------------------------------------------
# Name:        etgtools/pi_generator.py
# Author:      Robin Dunn
#
# Created:     18-Oct-2011
# Copyright:   (c) 2011-2020 by Total Control Software
# License:     wxWindows License
#---------------------------------------------------------------------------

"""
This generator will create "Python Interface" files, which define a skeleton
version of the classes, functions, attributes, docstrings, etc. as Python
code. This is useful for enabling some introspection of things located in
extension modules where there is less information available for
introspection. The .pi files are used by WingIDE for assisting with code
completion, displaying docstrings in the source assistant panel, etc.

NOTE: PyCharm has a similar feature but the file extension is .pyi in that
case.  For now we'll just make a copy of the .pi file, but PyCharm also
supports Python 3.5 style type annotations in the interface files so we may
want to add some type info to that version of the file eventually...
"""

import sys, os, re
from typing import Union
import etgtools.extractors as extractors
import etgtools.generators as generators
from etgtools.generators import nci, Utf8EncodingStream, textfile_open
from etgtools.tweaker_tools import FixWxPrefix, magicMethods, \
                                   guessTypeInt, guessTypeFloat, guessTypeStr


phoenixRoot = os.path.abspath(os.path.split(__file__)[0]+'/..')

#---------------------------------------------------------------------------

SKIP_PI_FILE = True

header_pi = """\
# -*- coding: utf-8 -*-
#---------------------------------------------------------------------------
# This file is generated by wxPython's PI generator.  Do not edit by hand.
#
# The *.pi files are used by WingIDE to provide more information than it is
# able to glean from introspection of extension types and methods.  They are
# not intended to be imported, executed or used for any other purpose other
# than providing info to the IDE.  If you don't use WingIDE you can safely
# ignore this file.
#
# See: https://wingware.com/doc/edit/helping-wing-analyze-code
#
# Copyright: (c) 2020 by Total Control Software
# License:   wxWindows License
#---------------------------------------------------------------------------

"""

SKIP_PYI_FILE = False

header_pyi = """\
# -*- coding: utf-8 -*-
#---------------------------------------------------------------------------
# This file is generated by wxPython's PI generator.  Do not edit by hand.
#
# The *.pyi files are used by PyCharm and other development tools to provide
# more information, such as PEP 484 type hints, than it is able to glean from
# introspection of extension types and methods.  They are not intended to be
# imported, executed or used for any other purpose other than providing info
# to the tools. If you don't use use a tool that makes use of .pyi files then
# you can safely ignore this file.
#
# See: https://www.python.org/dev/peps/pep-0484/
#      https://www.jetbrains.com/help/pycharm/2016.1/type-hinting-in-pycharm.html
#
# Copyright: (c) 2020 by Total Control Software
# License:   wxWindows License
#---------------------------------------------------------------------------

"""

typing_imports = """\
from __future__ import annotations
from enum import IntEnum, IntFlag, auto
from typing import (Any, overload, TypeAlias, TypeVar, ParamSpec, Generic,
    Union, Optional, List, Tuple, Callable
)
try:
    from typing import ParamSpec
except ImportError:
    from typing_extensions import ParamSpec

"""

#---------------------------------------------------------------------------

def piIgnored(obj):
    return getattr(obj, 'piIgnored', False)

#---------------------------------------------------------------------------

class PiWrapperGenerator(generators.WrapperGeneratorBase, FixWxPrefix):

    def generate(self, module, destFile=None):
        stream = Utf8EncodingStream()

        # process the module object and its child objects
        self.generateModule(module, stream)

        # Write the contents of the stream to the destination file
        if not destFile:
            name = module.module
            if name.startswith('_'):
                name = name[1:]
            destFile = os.path.join(phoenixRoot, 'wx', name)

        destFile_pi = destFile + '.pi'
        destFile_pyi = destFile + '.pyi'

        def _checkAndWriteHeader(destFile, header, docstring):
            if not os.path.exists(destFile):
                # create the file and write the header
                with textfile_open(destFile, 'wt') as f:
                    f.write(header)
                    if docstring:
                        f.write('\n"""\n%s"""\n' % docstring)

        if not SKIP_PI_FILE:
            _checkAndWriteHeader(destFile_pi, header_pi, module.docstring)
            self.writeSection(destFile_pi, 'typing-imports', typing_imports, at_end=False)
            self.writeSection(destFile_pi, module.name, stream.getvalue())

        if not SKIP_PYI_FILE:
            _checkAndWriteHeader(destFile_pyi, header_pyi, module.docstring)
            self.writeSection(destFile_pyi, 'typing-imports', typing_imports, at_end=False)
            self.writeSection(destFile_pyi, module.name, stream.getvalue())


    def writeSection(self, destFile, sectionName, sectionText, at_end = True):
        """
        Read all the lines from destFile, remove those currently between
        begin/end markers for sectionName (if any), and write the lines back
        to the file with the new text in sectionText.
        `at_end` determines where in the file the section is added when missing
        """
        sectionBeginLine = -1
        sectionEndLine = -1
        sectionBeginMarker = '#-- begin-%s --#' % sectionName
        sectionEndMarker = '#-- end-%s --#' % sectionName

        with textfile_open(destFile, 'rt') as fid:
            lines = fid.readlines()
        for idx, line in enumerate(lines):
            if line.startswith(sectionBeginMarker):
                sectionBeginLine = idx
            if line.startswith(sectionEndMarker):
                sectionEndLine = idx

        if sectionBeginLine == -1:
            if at_end:
                # not there already, add to the end
                lines.append(sectionBeginMarker + '\n')
                lines.append(sectionText)
                lines.append(sectionEndMarker + '\n')
            else:
                # not there already, add to the beginning
                # Skip the header
                idx = 0
                for idx, line in enumerate(lines):
                    if not line.startswith('#'):
                        break
                lines[idx+1:idx+1] = [
                    sectionBeginMarker + '\n',
                    sectionText,
                    sectionEndMarker + '\n',
                ]
        else:
            # replace the existing lines
            lines[sectionBeginLine+1:sectionEndLine] = [sectionText]

        with textfile_open(destFile, 'wt') as f:
            f.writelines(lines)

    #-----------------------------------------------------------------------
    def generateModule(self, module, stream):
        """
        Generate code for each of the top-level items in the module.
        """
        assert isinstance(module, extractors.ModuleDef)
        self.isCore = module.module == '_core'

        for item in module.imports:
            if item.startswith('_'):
                item = item[1:]
            if item == 'core':
                continue
            stream.write('import wx.%s\n' % item)

        # Move all PyCode items with an order value to the beginning of the
        # list as they most likely should appear before everything else.
        pycode = list()
        for item in module:
            if isinstance(item, extractors.PyCodeDef) and item.order is not None:
                pycode.append(item)
        for item in pycode:
            module.items.remove(item)
        module.items = pycode + module.items

        methodMap = {
            extractors.ClassDef         : self.generateClass,
            extractors.DefineDef        : self.generateDefine,
            extractors.FunctionDef      : self.generateFunction,
            extractors.EnumDef          : self.generateEnum,
            extractors.GlobalVarDef     : self.generateGlobalVar,
            extractors.TypedefDef       : self.generateTypedef,
            extractors.WigCode          : self.generateWigCode,
            extractors.PyCodeDef        : self.generatePyCode,
            extractors.PyFunctionDef    : self.generatePyFunction,
            extractors.PyClassDef       : self.generatePyClass,
            extractors.CppMethodDef     : self.generateCppMethod,
            extractors.CppMethodDef_sip : self.generateCppMethod_sip,
            }

        for item in module:
            if item.ignored or piIgnored(item):
                continue
            function = methodMap[item.__class__]
            function(item, stream)


    #-----------------------------------------------------------------------
    def generateEnum(self, enum, stream, indent=''):
        assert isinstance(enum, extractors.EnumDef)
        if enum.ignored or piIgnored(enum):
            return
        # These enum classes aren't actually accessible from the real wx
        # module, o we need to prepend _. But we want to make a type alias to
        # the non-prefixed name, so method signatures can reference it without
        # any special code, and also allow bare ints as inputs.
        if '@' in enum.name or not enum.name:
            # Anonymous enum
            enum_name = f"_enum_{enum.name.replace('@', '').strip()}"
            alias = ''
        else:
            alias = self.fixWxPrefix(enum.name)
            enum_name = f'_{alias}'
        if 'Flags' in enum_name:
            enum_type = 'IntFlag'
        else:
            enum_type = 'IntEnum'
        # Create the enum definition
        stream.write(f'\n{indent}class {enum_name}({enum_type}):\n')
        for v in enum.items:
            if v.ignored or piIgnored(v):
                continue
            name = v.pyName or v.name
            stream.write(f'{indent}    {name} = auto()\n')
        # Create the alias if needed
        if alias:
            stream.write(f'{indent}{alias}: TypeAlias = Union[{enum_name}, int]\n')
        # And bring the enum members into global scope.  We can't use
        # enum.global_enum for this because:
        #  1. It's only available on Python 3.11+
        #  2. FixWxPrefix wouldn't be able to pick up the names, since it's
        #     detecting based on AST parsing, not runtime changes (which
        #     enum.global_enum performs).
        for v in enum.items:
            if v.ignored or piIgnored(v):
                continue
            name = v.pyName or v.name
            stream.write(f'{indent}{name} = {enum_name}.{name}\n')

    #-----------------------------------------------------------------------
    def generateGlobalVar(self, globalVar, stream):
        assert isinstance(globalVar, extractors.GlobalVarDef)
        if globalVar.ignored or piIgnored(globalVar):
            return
        name = globalVar.pyName or globalVar.name
        valTyp = 'Any'
        if guessTypeInt(globalVar):
            valTyp = 'int'
        elif guessTypeFloat(globalVar):
            valTyp = 'float'
        elif guessTypeStr(globalVar):
            valTyp = 'str'
        elif globalVar.type:
            valTyp = self.cleanType(globalVar.type) or valTyp
        stream.write(f'{name}: {valTyp}\n')

    #-----------------------------------------------------------------------
    def generateDefine(self, define, stream):
        assert isinstance(define, extractors.DefineDef)
        if define.ignored or piIgnored(define):
            return
        # we're assuming that all #defines that are not ignored are integer or string values
        name = define.pyName or define.name
        if '"' in define.value:
            stream.write(f'{name}: str\n')
        else:
            stream.write(f'{name}: int\n')

    #-----------------------------------------------------------------------
    def generateTypedef(self, typedef, stream, indent=''):
        assert isinstance(typedef, extractors.TypedefDef)
        if typedef.ignored or piIgnored(typedef):
            return

        # If it's not a template instantiation, or has not been flagged by
        # the tweaker script that it should be treated as a class, then just
        # ignore the typedef and return.
        if not ('<' in typedef.type and '>' in typedef.type) and not typedef.docAsClass:
            return

        # Otherwise write a mock class for it that combines the template and class.
        # First, extract the info we need.
        if typedef.docAsClass:
            bases = [self.fixWxPrefix(b, True) for b in typedef.bases]
            name = self.fixWxPrefix(typedef.name)

        elif '<' in typedef.type and '>' in typedef.type:
            t = typedef.type.replace('>', '')
            t = t.replace(' ', '')
            bases = t.split('<')
            bases = [self.fixWxPrefix(b, True) for b in bases]
            name = self.fixWxPrefix(typedef.name)

        # Now write the Python equivalent class for the typedef
        if not bases:
            bases = ['object']  # this should not happen, but just in case...
        stream.write('%sclass %s(%s):\n' % (indent, name, ', '.join(bases)))
        indent2 = indent + ' '*4
        if typedef.briefDoc:
            stream.write('%s"""\n' % indent2)
            stream.write(nci(typedef.briefDoc, len(indent2)))
            stream.write('%s"""\n' % indent2)
        else:
            stream.write('%spass\n\n' % indent2)


    #-----------------------------------------------------------------------
    def generateWigCode(self, wig, stream, indent=''):
        assert isinstance(wig, extractors.WigCode)
        # write nothing for this one


    #-----------------------------------------------------------------------
    def generatePyCode(self, pc, stream, indent=''):
        assert isinstance(pc, extractors.PyCodeDef)
        code = pc.code
        if hasattr(pc, 'klass'):
            code = code.replace(pc.klass.pyName+'.', '')
        stream.write('\n')
        stream.write(nci(code, len(indent)))

    #-----------------------------------------------------------------------
    def generatePyFunction(self, pf, stream, indent=''):
        assert isinstance(pf, extractors.PyFunctionDef)
        stream.write('\n')
        if pf.deprecated:
            stream.write('%s@wx.deprecated\n' % indent)
        if pf.isStatic:
            stream.write('%s@staticmethod\n' % indent)
        stream.write('%sdef %s%s:\n' % (indent, pf.name, pf.argsString))
        indent2 = indent + ' '*4
        if pf.briefDoc:
            stream.write('%s"""\n' % indent2)
            stream.write(nci(pf.briefDoc, len(indent2)))
            stream.write('%s"""\n' % indent2)
        stream.write('%spass\n' % indent2)

    #-----------------------------------------------------------------------
    def generatePyClass(self, pc, stream, indent=''):
        assert isinstance(pc, extractors.PyClassDef)

        # write the class declaration and docstring
        if pc.deprecated:
            stream.write('%s@wx.deprecated\n' % indent)
        stream.write('%sclass %s' % (indent, pc.name))
        if pc.bases:
            stream.write('(%s):\n' % ', '.join(pc.bases))
        else:
            stream.write(':\n')
        indent2 = indent + ' '*4
        if pc.briefDoc:
            stream.write('%s"""\n' % indent2)
            stream.write(nci(pc.briefDoc, len(indent2)))
            stream.write('%s"""\n' % indent2)

        # these are the only kinds of items allowed to be items in a PyClass
        dispatch = {
            extractors.PyFunctionDef    : self.generatePyFunction,
            extractors.PyPropertyDef    : self.generatePyProperty,
            extractors.PyCodeDef        : self.generatePyCode,
            extractors.PyClassDef       : self.generatePyClass,
        }
        for item in pc.items:
            item.klass = pc
            f = dispatch[item.__class__]
            f(item, stream, indent2)



    #-----------------------------------------------------------------------
    def generateFunction(self, function, stream, is_overload=False):
        assert isinstance(function, extractors.FunctionDef)
        if not function.pyName:
            return
        if not is_overload and function.hasOverloads():
            for f in function.overloads:
                self.generateFunction(f, stream, True)
            stream.write('\n@overload')
        elif is_overload:
            stream.write('\n@overload')
        stream.write('\ndef %s' % function.pyName)
        argsString = function.pyArgsString
        if not argsString:
            argsString = '()'
        if '(' != argsString[0]:
            pos = argsString.find('(')
            argsString = argsString[pos:]
        argsString = argsString.replace('::', '.')
        stream.write(argsString)
        stream.write(':\n')
        if is_overload:
            stream.write('    ...\n')
        else:
            stream.write('    """\n')
            stream.write(nci(function.pyDocstring, 4))
            stream.write('    """\n')


    def generateParameters(self, parameters, stream, indent):
        def _lastParameter(idx):
            if idx == len(parameters)-1:
                return True
            for i in range(idx+1, len(parameters)):
                if not (parameters[i].ignored or piIgnored(parameters[i])):
                    return False
            return True

        for idx, param in enumerate(parameters):
            if param.ignored or piIgnored(param):
                continue
            stream.write(param.name)
            if param.default:
                stream.write('=%s' % param.default)
            if not _lastParameter(idx):
                stream.write(', ')


    #-----------------------------------------------------------------------
    def generateClass(self, klass, stream, indent=''):
        assert isinstance(klass, extractors.ClassDef)
        if klass.ignored or piIgnored(klass):
            return

        # check if there is a pi-customized version of the base class names
        if hasattr(klass, 'piBases'):
            bases = klass.piBases

        else:
            # check if it's a template with the template parameter as the base class
            bases = klass.bases[:]
            for tp in klass.templateParams:
                if tp in bases:
                    bases.remove(tp)

        # write class declaration
        klassName = klass.pyName or klass.name
        stream.write('\n%sclass %s' % (indent, klassName))
        if bases:
            stream.write('(')
            bases = [self.fixWxPrefix(b, True) for b in bases]
            stream.write(', '.join(bases))
            stream.write(')')
        stream.write(':\n')
        indent2 = indent + ' '*4

        # docstring
        stream.write('%s"""\n' % indent2)
        stream.write(nci(klass.pyDocstring, len(indent2)))
        stream.write('%s"""\n' % indent2)

        # generate nested classes
        for item in klass.innerclasses:
            self.generateClass(item, stream, indent2)

        # Split the items into public and protected groups
        enums = [i for i in klass if
                     isinstance(i, extractors.EnumDef) and
                     i.protection == 'public']
        ctors = [i for i in klass if
                     isinstance(i, extractors.MethodDef) and
                     i.protection == 'public' and (i.isCtor or i.isDtor)]
        public = [i for i in klass if i.protection == 'public' and
                     i not in ctors and i not in enums]
        protected = [i for i in klass if i.protection == 'protected']

        dispatch = {
            extractors.MemberVarDef     : self.generateMemberVar,
            extractors.TypedefDef       : lambda a,b,c: None,
            extractors.PropertyDef      : self.generateProperty,
            extractors.PyPropertyDef    : self.generatePyProperty,
            extractors.MethodDef        : self.generateMethod,
            extractors.EnumDef          : self.generateEnum,
            extractors.CppMethodDef     : self.generateCppMethod,
            extractors.CppMethodDef_sip : self.generateCppMethod_sip,
            extractors.PyMethodDef      : self.generatePyMethod,
            extractors.PyCodeDef        : self.generatePyCode,
            extractors.WigCode          : self.generateWigCode,
            }

        for item in enums:
            item.klass = klass
            self.generateEnum(item, stream, indent2)

        for item in ctors:
            if item.isCtor:
                item.klass = klass
                self.generateMethod(item, stream, indent2,
                                    name='__init__', docstring=klass.pyDocstring)

        for item in public:
            item.klass = klass
            f = dispatch[item.__class__]
            f(item, stream, indent2)

        for item in protected:
            item.klass = klass
            f = dispatch[item.__class__]
            f(item, stream, indent2)

        stream.write('%s# end of class %s\n\n' % (indent, klassName))


    def generateMemberVar(self, memberVar, stream, indent):
        assert isinstance(memberVar, extractors.MemberVarDef)
        if memberVar.ignored or piIgnored(memberVar):
            return
        member_type = memberVar.type
        if member_type:
            member_type = self.cleanType(member_type)
        if not member_type: # Unknown type for the member variable
            member_type = 'Any'
        stream.write(f'{indent}{memberVar.name}: {member_type}\n')


    def generateProperty(self, prop, stream, indent):
        assert isinstance(prop, extractors.PropertyDef)
        self._generateProperty(prop, stream, indent)


    def generatePyProperty(self, prop, stream, indent):
        assert isinstance(prop, extractors.PyPropertyDef)
        self._generateProperty(prop, stream, indent)

    def _generateProperty(self, prop: Union[extractors.PyPropertyDef, extractors.PropertyDef], stream, indent: str):
        if prop.ignored or piIgnored(prop):
            return
        if prop.setter and prop.getter:
            stream.write(f'{indent}{prop.name} = property({prop.getter}, {prop.setter})\n')
        elif prop.getter:
            stream.write(f'{indent}{prop.name} = property({prop.getter})\n')
        elif prop.setter:
            stream.write(f'{indent}{prop.name} = property(fset={prop.setter})\n') 


    def generateMethod(self, method, stream, indent, name=None, docstring=None, is_overload=False):
        assert isinstance(method, extractors.MethodDef)
        for m in method.all():  # use the first not ignored if there are overloads
            if not m.ignored or piIgnored(m):
                method = m
                break
        else:
            return
        if method.isDtor:
            return

        name = name or method.pyName or method.name
        if name in magicMethods:
            name = magicMethods[name]

        # write the method declaration
        if not is_overload and method.hasOverloads():
            for m in method.overloads:
                self.generateMethod(m, stream, indent, name, None, True)
            stream.write(f'\n{indent}@overload')
        elif is_overload:
            stream.write(f'\n{indent}@overload')
        if method.isStatic:
            stream.write('\n%s@staticmethod' % indent)
        stream.write('\n%sdef %s' % (indent, name))
        argsString = method.pyArgsString
        if not argsString:
            argsString = '()'
        if '(' != argsString[0]:
            pos = argsString.find('(')
            argsString = argsString[pos:]
        if not method.isStatic:
            if argsString == '()':
                argsString = '(self)'
            else:
                argsString = '(self, ' + argsString[1:]
        argsString = argsString.replace('::', '.')
        stream.write(argsString)
        stream.write(':\n')
        indent2 = indent + ' '*4

        # docstring
        if is_overload:
            stream.write(f'{indent2}...\n')
        else:
            if not docstring:
                if hasattr(method, 'pyDocstring'):
                    docstring = method.pyDocstring
                else:
                    docstring = ""
            stream.write('%s"""\n' % indent2)
            if docstring.strip():
                stream.write(nci(docstring, len(indent2)))
            stream.write('%s"""\n' % indent2)



    def generateCppMethod(self, method, stream, indent=''):
        assert isinstance(method, extractors.CppMethodDef)
        self.generateMethod(method, stream, indent)


    def generateCppMethod_sip(self, method, stream, indent=''):
        assert isinstance(method, extractors.CppMethodDef_sip)
        self.generateMethod(method, stream, indent)


    def generatePyMethod(self, pm, stream, indent):
        assert isinstance(pm, extractors.PyMethodDef)
        if pm.ignored or piIgnored(pm):
            return
        if pm.isStatic:
            stream.write('\n%s@staticmethod' % indent)
        stream.write('\n%sdef %s' % (indent, pm.name))
        stream.write(getattr(pm, 'piArgsString', pm.argsString))
        stream.write(':\n')
        indent2 = indent + ' '*4

        stream.write('%s"""\n' % indent2)
        stream.write(nci(pm.pyDocstring, len(indent2)))
        stream.write('%s"""\n' % indent2)




#---------------------------------------------------------------------------
#---------------------------------------------------------------------------
