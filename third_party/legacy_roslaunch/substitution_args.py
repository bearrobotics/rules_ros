# Software License Agreement (BSD License)
#
# Copyright (c) 2008, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Revision $Id: substitution_args.py 15178 2011-10-10 21:22:53Z kwc $
"""
Library for processing XML substitution args. This is currently used
by roslaunch and xacro, but it is not yet a top-level ROS feature.
"""

# pylint: disable=eval-used
# pylint: disable=line-too-long

import math
import os
import glob
from io import StringIO  # Python 3.x

import rosgraph.names

import yaml
from third_party.legacy_roslaunch.loader import convert_value

_bearfile = None

class SubstitutionException(Exception):
    """
    Base class for exceptions in substitution_args routines
    """


class ArgException(SubstitutionException):
    """
    Exception for missing $(arg) values
    """


def _eval_env(name):
    try:
        return os.environ[name]
    except KeyError as e:
        raise SubstitutionException("environment variable %s is not set" %
                                    str(e)) from e


def _env(resolved, a, args, _context):
    """
    process $(env) arg
    @return: updated resolved argument
    @rtype: str
    @raise SubstitutionException: if arg invalidly specified
    """
    if len(args) != 1:
        raise SubstitutionException(
            "$(env var) command only accepts one argument [%s]" % a)
    return resolved.replace("$(%s)" % a, _eval_env(args[0]))


def _eval_optenv(name, default=''):
    if name in os.environ:
        return os.environ[name]
    return default


def _optenv(resolved, a, args, _context):
    """
    process $(optenv) arg
    @return: updated resolved argument
    @rtype: str
    @raise SubstitutionException: if arg invalidly specified
    """
    if len(args) == 0:
        raise SubstitutionException(
            "$(optenv var) must specify an environment variable [%s]" % a)
    return resolved.replace("$(%s)" % a,
                            _eval_optenv(args[0], default=' '.join(args[1:])))


def _eval_anon(idd, anons):
    if idd in anons:
        return anons[idd]
    resolve_to = rosgraph.names.anonymous_name(idd)
    anons[idd] = resolve_to
    return resolve_to


def _anon(resolved, a, args, context):
    """
    process $(anon) arg
    @return: updated resolved argument
    @rtype: str
    @raise SubstitutionException: if arg invalidly specified
    """
    # #1559 #1660
    if len(args) == 0:
        raise SubstitutionException("$(anon var) must specify a name [%s]" % a)
    elif len(args) > 1:
        raise SubstitutionException(
            "$(anon var) may only specify one name [%s]" % a)
    if 'anon' not in context:
        context['anon'] = {}
    anon_context = context['anon']
    return resolved.replace("$(%s)" % a,
                            _eval_anon(idd=args[0], anons=anon_context))


def _eval_dirname(filename):
    if not filename:
        raise SubstitutionException(
            "Cannot substitute $(dirname), no file/directory information available."
        )
    return os.path.abspath(os.path.dirname(filename))


def _dirname(resolved, a, _args, context):
    """
    process $(dirname)
    @return: updated resolved argument
    @rtype: str
    @raise SubstitutionException: if no information about the current launch file is available, for example
           if XML was passed via stdin, or this is a remote launch.
    """
    return resolved.replace("$(%s)" % a,
                            _eval_dirname(context.get('filename', None)))

def _get_bearfile():
    global _bearfile
    if _bearfile is None:
        if 'BEAR_CONFIG' not in os.environ:
            raise SubstitutionException('BEAR_CONFIG not found')
        filename = os.environ['BEAR_CONFIG']
        with open(filename) as f:
            try:
                _bearfile = yaml.load(f)
                return _bearfile
            except:
                raise SubstitutionException('Cannot parse bear config file %s' % filename)
        raise SubstitutionException('Cannot open bear config file %s' % filename)
    else:
        return _bearfile

def _extract_bearconfig(arg, config):
    paths = arg.split('.')
    for path in paths:
        if path not in config:
            raise SubstitutionException('Cannot find given config path %s' % path)
        config = config[path]
    return config

def _bearconfig(resolved, a, args, context):
    """
    process $(bearconfig PATH)
    :returns: found config, ``str``
    :raises: :exc:SubstitutionException: if $(bearconfig PATH) substitution failed
    """
    if len(args) != 1:
        raise SubstitutionException('$(bearconfig PATH) command only accepts one argument [%s]' % a)
    config = _extract_bearconfig(args[0], _get_bearfile())
    result = yaml.dump(config)
    if result.endswith('\n...\n'):  # trim explicit yaml ending mark
        result = result[:-5]
    # Remove trailing newlines
    result = result.rstrip('\n')
    # Remove single quotations - yaml considered strings
    result = result.strip("'")
    return result

def _eval_find(pkg):
    raise SubstitutionException("`find` is deprecated!")


def _find(resolved, a, args, context):
    """
    process $(find PKG)
    Resolves the path while considering the path following the command to provide backward compatible results.
    If it is followed by a path it first tries to resolve it as an executable and than as a normal file under share.
    Else it resolves to the source share folder of the PKG.
    :returns: updated resolved argument, ``str``
    :raises: :exc:SubstitutionException: if PKG invalidly specified
    :raises: :exc:`rospkg.ResourceNotFound` If PKG requires resource (e.g. package) that does not exist
    """
    _, after = _split_command(resolved, a)
    path, after = _separate_first_path(after)

    # WARNING: this is heavily modified from the original $(find).
    # This picks the first result of glob('**/<package>') so there can be side effects.
    # e.g) $(find dynamic_client) => 'ROS/system_control/dynamic_client'
    dirs = glob.glob(f"**/{args[0]}", recursive=True)
    return os.getcwd() + "/" + dirs[0] + path


def _find_executable(resolved, a, args, _context, source_path_to_packages=None):
    """
    process $(find-executable PKG PATH)
    It finds the executable with the basename(PATH) in the libexec folder
    or under the PATH relative to the package.xml file.
    :returns: updated resolved argument, ``str``
    :raises: :exc:SubstitutionException: if PKG/PATH invalidly specified or executable is not found for PKG
    """
    raise SubstitutionException("$(find-executable pkg path) is deprecated!")


def _find_resource(resolved, a, args, _context, source_path_to_packages=None):
    """
    process $(find-resource PKG PATH)
    Resolves the relative PATH from the share folder of the PKG either from install space, devel space or from the source folder.
    :returns: updated resolved argument, ``str``
    :raises: :exc:SubstitutionException: if PKG and PATH invalidly specified or relative PATH is not found for PKG
    """
    raise SubstitutionException("$(find-resource pkg path) is deprecated!")


def _split_command(resolved, command_with_args):
    cmd = '$(%s)' % command_with_args
    idx1 = resolved.find(cmd)
    idx2 = idx1 + len(cmd)
    return resolved[0:idx1], resolved[idx2:]


def _separate_first_path(value):
    idx = value.find(' ')
    if idx < 0:
        path, rest = value, ''
    else:
        path, rest = value[0:idx], value[idx:]
    return path, rest


def _sanitize_path(path):
    path = path.replace('/', os.sep)
    path = path.replace('\\', os.sep)
    return path


def _get_executable_path(base_path, path):
    full_path = os.path.join(base_path, path)
    if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
        return full_path
    return None


def _eval_arg(name, args):
    try:
        return args[name]
    except KeyError as ex:
        raise ArgException(name) from ex


def _arg(resolved, a, args, context):
    """
    process $(arg) arg

    :returns: updated resolved argument, ``str``
    :raises: :exc:`ArgException` If arg invalidly specified
    """
    if len(args) == 0:
        raise SubstitutionException(
            "$(arg var) must specify a variable name [%s]" % (a))
    elif len(args) > 1:
        raise SubstitutionException("$(arg var) may only specify one arg [%s]" %
                                    (a))

    if 'arg' not in context:
        context['arg'] = {}
    return resolved.replace("$(%s)" % a,
                            _eval_arg(name=args[0], args=context['arg']))


# Create a dictionary of global symbols that will be available in the eval
# context.  We disable all the builtins, then add back True and False, and also
# add true and false for convenience (because we accept those lower-case strings
# as boolean values in XML).
_eval_dict = {
    'true': True,
    'false': False,
    'True': True,
    'False': False,
    '__builtins__': {
        k: __builtins__[k]
        for k in ['list', 'dict', 'map', 'str', 'float', 'int']
    },
    'env': _eval_env,
    'optenv': _eval_optenv,
    'find': _eval_find
}
# also define all math symbols and functions
_eval_dict.update(math.__dict__)


class _DictWrapper(object):

    def __init__(self, args, functions):
        self._args = args
        self._functions = functions

    def __getitem__(self, key):
        try:
            return self._functions[key]
        except KeyError:
            return convert_value(self._args[key], 'auto')


def _eval(s, context):
    if 'anon' not in context:
        context['anon'] = {}
    if 'arg' not in context:
        context['arg'] = {}

    # inject correct anon context
    def _eval_anon_context(idd):
        return _eval_anon(idd, anons=context['anon'])

    # inject arg context
    def _eval_arg_context(name):
        return convert_value(_eval_arg(name, args=context['arg']), 'auto')

    # inject dirname context
    def _eval_dirname_context():
        return _eval_dirname(context['filename'])

    functions = {
        'anon': _eval_anon_context,
        'arg': _eval_arg_context,
        'dirname': _eval_dirname_context
    }
    functions.update(_eval_dict)

    # ignore values containing double underscores (for safety)
    # http://nedbatchelder.com/blog/201206/eval_really_is_dangerous.html
    if s.find('__') >= 0:
        raise SubstitutionException(
            "$(eval ...) may not contain double underscore expressions")
    return str(eval(s, {}, _DictWrapper(context['arg'], functions)))


def resolve_args(arg_str, context=None, resolve_anon=True, _filename=None):
    """
    Resolves substitution args (see wiki spec U{http://ros.org/wiki/roslaunch}).

    @param arg_str: string to resolve zero or more substitution args
        in. arg_str may be None, in which case resolve_args will
        return None
    @type  arg_str: str
    @param context dict: (optional) dictionary for storing results of
        the 'anon' and 'arg' substitution args. multiple calls to
        resolve_args should use the same context so that 'anon'
        substitions resolve consistently. If no context is provided, a
        new one will be created for each call. Values for the 'arg'
        context should be stored as a dictionary in the 'arg' key.
    @type  context: dict
    @param resolve_anon bool: If True (default), will resolve $(anon
        foo). If false, will leave these args as-is.
    @type  resolve_anon: bool

    @return str: arg_str with substitution args resolved
    @rtype:  str
    @raise SubstitutionException: if there is an error resolving substitution args
    """
    if context is None:
        context = {}
    if not arg_str:
        return arg_str
    # special handling of $(eval ...)
    if arg_str.startswith('$(eval ') and arg_str.endswith(')'):
        return _eval(arg_str[7:-1], context)
    # first resolve variables like 'env' and 'arg'
    commands = {
        'env': _env,
        'optenv': _optenv,
        'dirname': _dirname,
        'anon': _anon,
        'arg': _arg,
    }
    resolved = _resolve_args(arg_str, context, resolve_anon, commands)
    # then resolve 'find' as it requires the subsequent path to be expanded already
    commands = {
        'find': _find,
        'bearconfig': _bearconfig,
    }
    resolved = _resolve_args(resolved, context, resolve_anon, commands)
    return resolved


def _resolve_args(arg_str, context, _resolve_anon, commands):
    valid = ['bearconfig', 'find', 'env', 'optenv', 'dirname', 'anon', 'arg']
    resolved = arg_str
    for a in _collect_args(arg_str):
        splits = [s for s in a.split(' ') if s]
        if not splits[0] in valid:
            raise SubstitutionException(
                "Unknown substitution command [%s]. Valid commands are %s" %
                (a, valid))
        command = splits[0]
        args = splits[1:]
        if command in commands:
            resolved = commands[command](resolved, a, args, context)
    return resolved


_OUT = 0
_DOLLAR = 1
_LP = 2
_IN = 3


def _collect_args(arg_str):
    """
    State-machine parser for resolve_args. Substitution args are of the form:
    $(find package_name)/scripts/foo.py $(export some/attribute blar) non-relevant stuff

    @param arg_str: argument string to parse args from
    @type  arg_str: str
    @raise SubstitutionException: if args are invalidly specified
    @return: list of arguments
    @rtype: [str]
    """
    buff = StringIO()
    args = []
    state = _OUT
    for c in arg_str:
        # No escapes supported
        if c == '$':
            if state == _OUT:
                state = _DOLLAR
            elif state == _DOLLAR:
                pass
            else:
                raise SubstitutionException(
                    "Dollar signs '$' cannot be inside of substitution args [%s]"
                    % arg_str)
        elif c == '(':
            if state == _DOLLAR:
                state = _LP
            elif state != _OUT:
                raise SubstitutionException(
                    "Invalid left parenthesis '(' in substitution args [%s]" %
                    arg_str)
        elif c == ')':
            if state == _IN:
                #save contents of collected buffer
                args.append(buff.getvalue())
                buff.truncate(0)
                buff.seek(0)
                state = _OUT
            else:
                state = _OUT
        elif state == _DOLLAR:
            # left paren must immediately follow dollar sign to enter _IN state
            state = _OUT
        elif state == _LP:
            state = _IN

        if state == _IN:
            buff.write(c)
    return args
