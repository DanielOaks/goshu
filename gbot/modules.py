#!/usr/bin/env python3
# Goshu IRC Bot
# written by Daniel Oaks <daniel@danieloaks.net>
# licensed under the ISC license

import imp
import importlib
import inspect
import json
import os
import threading

from girc.formatting import escape
from girc.utils import NickMask

from .commands import AdminCommand, Command, UserCommand, standard_admin_commands
from .info import InfoStore
from .libs.helper import JsonHandler, add_path
from .users import user_levels, USER_LEVEL_NOPRIVS, USER_LEVEL_ADMIN

LISTENER_HIGHEST_PRIORITY = -30
LISTENER_HIGHER_PRIORITY = -20
LISTENER_HIGH_PRIORITY = -10
LISTENER_NORMAL_PRIORITY = 0
LISTENER_LOW_PRIORITY = 10
LISTENER_LOWER_PRIORITY = 20
LISTENER_LOWEST_PRIORITY = 30

listener_priorities = {
    'highest': LISTENER_HIGHEST_PRIORITY,
    'higher': LISTENER_HIGHER_PRIORITY,
    'high': LISTENER_HIGH_PRIORITY,
    'normal': LISTENER_NORMAL_PRIORITY,
    'low': LISTENER_LOW_PRIORITY,
    'lower': LISTENER_LOWER_PRIORITY,
    'lowest': LISTENER_LOWEST_PRIORITY,
}


def extract_mod_info_from_docstring(docstring, name, handler):
    """Extracts module info from the given docstring.

    Basically, lines starting with @ represent 'variable lines' and their
    values are extracted and put into the returned dictionary.

    Args:
        docstring: Docstring we're extracting info from
        name: Original name
        handler: Handler function
    """
    if name:
        info_type = 'command'
    elif name is None:
        info_type = 'listener'

    # command
    if info_type == 'command' and len(docstring.split('\n')) < 2:
        return {
            name: {
                'name': [name],
                'description': ['--- {}'.format(docstring.strip())],
                'call': handler,
            }
        }

    # extract info
    if info_type == 'command':
        info = {
            'name': [name],
            'aliases': {},
            'call': handler,
            'description': [docstring.split('\n')[0].strip()]
        }
    elif info_type == 'listener':
        listeners = []
        info = {
            'call': handler,
        }

    for line in docstring.split('\n'):
        if line.lstrip().startswith('@'):
            line_info = line.lstrip().lstrip('@').split(' ', 1)

            if len(line_info) < 2:
                name = line_info[0].casefold()
                val = True
            else:
                name, val = line_info
                name = name.casefold()
            name = name.replace('-', '_')

            if name == 'alias':
                if '---' in val:
                    alias_name, alias_desc = val.split('---')
                    alias_name = alias_name.strip()
                    alias_desc = alias_desc.strip()
                    info['aliases'][alias_name] = alias_desc
                else:
                    info['name'].append(val.strip().lower())

            elif name in ['channel_mode_restriction', 'chanrestrict', 'chan_restrict']:
                if val == True:
                    val = 'h'
                info['channel_mode_restriction'] = val

            elif name in ['usage', 'description']:
                if name not in info:
                    info[name] = [val]
                else:
                    info[name].append(val)

            elif name == 'listen':
                values = val.split()

                inline = False
                if 'inline' in values:
                    inline = True
                    values.remove('inline')
                info['inline'] = inline

                if len(values) < 2:
                    direction = 'in'
                    event_type = values[0]
                    priority = LISTENER_NORMAL_PRIORITY

                    # let people use the names defined in listener_priorities
                    priority = listener_priorities.get(priority, priority)
                elif len(values) > 2:
                    direction, event_type, priority = values

                    # let people use the names defined in listener_priorities
                    priority = listener_priorities.get(priority, priority)
                else:
                    direction, event_type = values
                    priority = LISTENER_NORMAL_PRIORITY

                info['priority'] = int(priority)

                info['direction'] = direction
                info['event_type'] = event_type

                listeners.append(info)
                info = {
                    'call': handler,
                }
            else:
                info[name] = val

    if info_type == 'listener':
        return listeners

    if info.get('usage'):
        desc_lines = info.get('description')
        usage_lines = info.get('usage')
        del info['usage']

        info['description'] = []

        for i, use in enumerate(usage_lines):
            if len(desc_lines) >= i + 1:
                desc = desc_lines[i]
            else:
                desc = desc_lines[-1]
            info['description'].append('{} --- {}'.format(use, desc))
    elif info.get('description'):
        info['description'] = '--- {}'.format(info['description'])

    module_dict = {}

    if len(info['name']):
        names = info['name'][0]
    else:
        names = info['name']
    aliases = info['aliases']
    del info['aliases']

    module_dict[names] = info

    for name, desc in aliases.items():
        new_info = dict(info)
        new_info['name'] = [name]
        new_info['description'] = desc

        module_dict[name] = new_info

    return module_dict


# special custom json encoder
class IEncoder(json.JSONEncoder):
    def default(self, o):
        try:
            return o.__json__()
        except:
            return o


def json_dumps(*pargs, **kwargs):
    """Special json dumper to use our __json__ function where appropriate."""
    return json.dumps(*pargs, cls=IEncoder, **kwargs)


class Module:
    """Module to add commands/functionality to the bot."""
    # whether this module is 'core', or practically required for
    #   Goshu to operate
    core = False
    standard_admin_commands = []
    custom_store = None

    def __init__(self, bot):
        self.bot = bot

        if getattr(self, 'name', None) is None:
            self.name = self.__class__.__name__

        if getattr(self, 'ext', None) is None:
            if len(self.name) >= 3:
                self.ext = self.name[:3]
            else:
                self.ext = self.name

        self.dynamic_path = os.path.join('.', 'modules', self.name)

        self.admin_commands = {}
        self.commands = {}
        self.static_commands = {}
        self.json_handlers = []
        self.dynamic_commands = {}

        self.store_filename = os.sep.join(['config', 'modules', '{}.json'.format(self.name)])
        if self.custom_store:
            self.store = self.custom_store(self.bot, self.store_filename)
        else:
            self.store = InfoStore(self.bot, self.store_filename)

        # load commands into our events dictionary
        self.events = {
            'commands': {},
            'admin': {},
        }
        for name, handler in inspect.getmembers(self):
            if handler.__doc__ is None:
                continue

            if name.startswith('acmd_'):
                name = name.split('_', 1)[-1]
                info = extract_mod_info_from_docstring(handler.__doc__, name, handler)

                for cmd_name, cmd_info in info.items():
                    cmd = self.bot.modules.return_admin_command_dict(self, cmd_info)
                    if cmd_info.get('global', False):
                        for cmdn in cmd:
                            cmd[cmdn].module_name = self.name

                            if cmdn not in self.bot.modules.global_admin_commands:
                                self.bot.modules.global_admin_commands[cmdn] = []
                            self.bot.modules.global_admin_commands[cmdn].append(cmd[cmdn])
                    else:
                        self.admin_commands.update(cmd)

            elif name.startswith('cmd_'):
                name = name.split('_', 1)[-1]
                info = extract_mod_info_from_docstring(handler.__doc__, name, handler)

                for cmd_name, cmd_info in info.items():
                    cmd = self.bot.modules.return_command_dict(self, cmd_info)
                    self.static_commands.update(cmd)

            elif name.endswith('_listener'):
                info = extract_mod_info_from_docstring(handler.__doc__, None, handler)

                for listener in info:
                    inline = listener['inline']
                    priority = listener['priority']
                    direction = listener['direction']
                    event_type = listener['event_type']

                    if direction not in self.events:
                        self.events[direction] = {}
                    if event_type not in self.events[direction]:
                        self.events[direction][event_type] = []

                    if inline:
                        listn = (priority, handler, inline)
                    else:
                        listn = (priority, handler)

                    self.events[direction][event_type].append(listn)

        self.commands.update(self.static_commands)

    def load(self):
        """Actually start up everything we need"""
        if os.path.exists(self.dynamic_path):
            # setup our new module's dynamic json command handler
            new_handler = JsonHandler(self, self.dynamic_path, **{
                'attr': 'dynamic_commands',
                'callback_name': '_json_command_callback',
                'ext': self.ext,
                'yaml': True,
            })
            self.json_handlers.append(new_handler)
            self.reload_json()

        self.commands.update(self.static_commands)

    def is_ignored(self, target):
        """Whether the target is ignored in our config."""
        if isinstance(target, str):
            if target[0] == '#':  # XXX - this is crap
                target = target
            else:
                target = NickMask(target).nick
        else:
            if target.is_user:
                target = target.nick
            elif target.is_channel:
                target = target.name

        # XXX - this lower should be based on server, like '#' check above
        return target.lower() in self.store.get('ignored', [])

    def combined(self, event, command, usercommand):
        ...

    def unload(self):
        pass

    def reload_json(self):
        """Reload any json handlers we have."""
        for json_h in self.json_handlers:
            json_h.reload()

    def get_required_values(self, name):
        """Get 'required values' for given name."""
        values = {}
        for var_name, var_info in self.store.get('required_values', {}).get(name, {}).items():
            key = ('required_values', name, var_name)
            var_value = self.store.get(key)
            values[var_name] = var_value
        return values

    def parse_required_value(self, base_name, name, info):
        """Parse required value and put it into our store."""
        if not self.store.has_key('required_values'):
            self.store.set('required_values', {})

        var_key = ['required_values', base_name, name]

        var_type = info.get('type', 'str')
        if 'type' in info:
            del info['type']

        if var_type == 'str':
            var_type = str
        elif var_type == 'int':
            var_type = int
        elif var_type == 'float':
            var_type = float
        elif var_type == 'bool':
            var_type = bool
        else:
            raise Exception('key type not in list:', var_type)

        prompt = info.get('prompt', name)
        if 'prompt' in info:
            del info['prompt']
        if isinstance(prompt, str):
            prompt = prompt.rstrip() + ' '

        self.store.add_key(var_type, var_key, prompt, **info)

    def _json_command_callback(self, new_json):
        """Update our command dictionary.
        Mixes new json dynamic commands with our static ones.
        """
        # assemble new json dict into actual commands dict
        new_commands = {}
        disabled_commands = getattr(self.bot, 'settings', {}).get('dynamic_commands_disabled', {}).get(self.name.lower(), [])
        for key, info in new_json.items():
            if key in disabled_commands:
                continue

            single_command_dict = self.bot.modules.return_command_dict(self, info)
            new_commands.update(single_command_dict)

            for var_name, var_info in info.get('required_values', {}).items():
                base_command_name = info['name'][0]
                self.parse_required_value(base_command_name, var_name, var_info)

        # merge new dynamic commands with static ones
        commands = getattr(self, 'static_commands', {}).copy()
        commands.update(new_commands)
        commands.update(getattr(self, 'static_commands', {}))

        self.commands = commands


def isModule(member):
    if member in Module.__subclasses__():
        return True
    return False


class Modules:
    """Manages goshubot's modules."""
    def __init__(self, bot, path):
        self.bot = bot
        self.whole_modules = {}
        self.modules = {}
        self.path = path
        add_path(path)
        self.global_admin_commands = {}

        # event listeners
        self.listeners = {}

        # info lists
        self.all_module_names = []
        self.core_module_names = []
        self.dcm_module_commands = {}  # dynamic command module command lists

    def load_module_info(self):
        modules = self._modules_from_path()

        # load so we can work out which modules are core and which aren't
        for mod_name in modules:
            loaded_module = self.load(mod_name)
            self.modules[mod_name].load()
            if mod_name not in self.all_module_names:
                self.all_module_names.append(mod_name)
            if self.modules[mod_name].core:
                self.core_module_names.append(mod_name)
            if self.modules[mod_name].dynamic_commands:
                self.dcm_module_commands[mod_name] = list(self.modules[mod_name].dynamic_commands.keys())
            self.unload(mod_name)

    def _modules_from_path(self, path=None):
        if path is None:
            path = self.path

        modules = []
        for entry in os.listdir(path):
            if os.path.isfile(os.path.join(path, entry)):
                (name, ext) = os.path.splitext(entry)
                if ext == os.extsep + 'py' and name != '__init__':
                    modules.append(name)
            elif os.path.isfile((os.path.join(path, entry, os.extsep.join(['__init__', 'py'])))):
                modules.append(entry)
        return modules

    def load_init(self):
        modules = self._modules_from_path()
        output = 'modules '
        disabled_modules = self.bot.settings.get('disabled_modules', [])
        for module in modules:
            loaded_module = self.load(module)
            if self.modules[module].name.lower() in disabled_modules:
                self.unload(module)
            else:
                self.modules[module].load()
                if loaded_module:
                    output += ', '.join(self.whole_modules[module]) + ', '
                else:
                    output += module + '[FAILED], '
        output = output[:-2]
        output += ' loaded'
        self.bot.gui.put_line(output)

    def load(self, name):
        whole_module = importlib.import_module(name)
        imp.reload(whole_module)  # so reloading works

        # find the actual goshu Module(s) we wanna load from the whole module
        modules = []
        for item in inspect.getmembers(whole_module, isModule):
            modules.append(item[1](self.bot))
            break
        if not modules:
            return False

        # if /any/ are dupes, exit
        for module in modules:
            if module.name in self.modules:
                return False

        self.whole_modules[name] = []

        for module in modules:
            self.whole_modules[name].append(module.name)
            self.modules[module.name] = module

            # add standard admin commands
            if module.standard_admin_commands:
                for name in module.standard_admin_commands:
                    if name not in standard_admin_commands:
                        raise Exception('Module {} cannot load, standard admin command {} does not exist'.format(module.name, name))

                    handler = standard_admin_commands[name]

                    new_name = '_standard_admin_command_{}'.format(name)
                    setattr(module, new_name, handler)
                    hand = getattr(module, new_name, None)

                    info = extract_mod_info_from_docstring(handler.__doc__, name, hand)

                    # add standard info
                    if 'call_level' not in info[name]:
                        info[name]['call_level'] = USER_LEVEL_ADMIN
                    if 'view_level' not in info[name]:
                        info[name]['view_level'] = info[name]['call_level']

                    info[name]['bound'] = False

                    command = AdminCommand(**info[name])

                    module.admin_commands[name] = command

            if not getattr(module, 'events', None):
                module.events = {}

            # add event listeners
            for direction in ['in', 'out', 'both']:
                for event_name, handlers in module.events.get(direction, {}).items():
                    for info in handlers:
                        if len(info) < 3:
                            priority, handler = info
                            inline = False
                        else:
                            priority, handler, inline = info

                        if priority not in self.listeners:
                            self.listeners[priority] = {}
                        if direction not in self.listeners[priority]:
                            self.listeners[priority][direction] = {}
                        if event_name not in self.listeners[priority][direction]:
                            self.listeners[priority][direction][event_name] = []

                        self.listeners[priority][direction][event_name].append((handler, inline))

            for command in module.events.get('commands', {}):
                self.add_command_info(module.name, command)
            module.folder_path = os.path.join('modules', name)
            module.bot = self.bot

        return True

    def unload(self, name):
        if name not in self.whole_modules:
            self.bot.gui.put_line('module', name, 'not in', self.whole_modules)
            return False

        for modname in self.whole_modules[name]:
            # remove global listeners
            for cmd in self.bot.modules.global_admin_commands:
                for handler in list(self.bot.modules.global_admin_commands[cmd]):
                    if handler.module_name == self.modules[modname].name:
                        self.bot.modules.global_admin_commands[cmd].remove(handler)

            # remove event listeners
            for direction in ['both', 'in', 'out']:
                for event_name, handlers in self.modules[modname].events.get(direction, {}).items():
                    for info in handlers:
                        if len(info) < 3:
                            priority, handler = info
                            inline = False
                        else:
                            priority, handler, inline = info

                        self.listeners[priority][direction][event_name].remove((handler, inline))

                        # clear old dicts if not being used anymore
                        if not self.listeners[priority][direction][event_name]:
                            del self.listeners[priority][direction][event_name]
                        if not self.listeners[priority][direction]:
                            del self.listeners[priority][direction]
                        if not self.listeners[priority]:
                            del self.listeners[priority]

            self.modules[modname].unload()
            del self.modules[modname]

        del self.whole_modules[name]
        return True

    def handle(self, event):
        # add source_user_level convenience variable for priv/pubmsg
        if event['verb'] in ('privmsg', 'pubmsg') and event['direction'] == 'in':
            event['source_account'] = self.bot.accounts.account(event['server'], event['source'])
            event['source_user_level'] = self.bot.accounts.access_level(event['source_account'])

        # call listeners
        called = []
        for priority in sorted(self.listeners.keys()):
            for search_direction in ['both', event['direction']]:
                for search_type in ['all', event['verb']]:
                    for handler, inline in self.listeners[priority].get(search_direction, {}).get(search_type, []):
                        if handler not in called:
                            called.append(handler)

                            # if inline, handler can change event as it goes through
                            #   if they return anything that's not None
                            if inline:
                                new_event = handler(event)
                                if new_event is not None:
                                    event = new_event
                            else:
                                threading.Thread(target=handler, args=[event]).start()

        # then handle commands
        if event['verb'] in ('privmsg', 'pubmsg') and event['direction'] == 'in':
            self.handle_command(event)
        if event['verb'] == 'privmsg' and event['direction'] == 'in':
            self.handle_admin_command(event)

    def handle_admin_command(self, event):
        if event['message'].startswith(escape(self.bot.settings.store['admin_command_prefix'])):
            admin_prefix_len = len(escape(self.bot.settings.store['admin_command_prefix']))
            in_string = event['message'][admin_prefix_len:].strip()
            if not in_string:
                return  # empty

            command_list = in_string.split(' ', 2)
            module_name = command_list[0].lower()

            original_command_args = ' '.join(command_list[1:])

            if len(command_list) > 1:
                command_name = command_list[1].lower()
            else:
                command_name = ''

            if len(command_list) < 3:
                command_args = ''
            else:
                command_args = command_list[2]

            useraccount = self.bot.accounts.account(event['server'], event['source'])
            if useraccount:
                userlevel = self.bot.accounts.access_level(useraccount)
            else:
                userlevel = USER_LEVEL_NOPRIVS

            # get list of handlers
            handler_list = []

            if module_name in self.global_admin_commands:
                for command_info in self.global_admin_commands[module_name]:
                    handler_list.append((command_info, True))
            if module_name in self.modules:
                if command_name in self.modules[module_name].admin_commands:
                    command_info = self.modules[module_name].admin_commands[command_name]
                    handler_list.append((command_info, False))

            for command_info, is_global in handler_list:
                if userlevel >= command_info.call_level:
                    if command_info.bound:
                        args = []
                    else:
                        args = [self.modules[module_name]]

                    if is_global:
                        usercmd = UserCommand(module_name, original_command_args)
                    else:
                        usercmd = UserCommand(command_name, command_args)

                    args += [event, command_info, usercmd]

                    threading.Thread(target=command_info.call,
                                     args=args).start()
                else:
                    self.bot.gui.put_line('        No Privs')

    def handle_command(self, event):
        if event['message'].startswith(escape(self.bot.settings.store['command_prefix'])):
            in_string = event['message'][len(escape(self.bot.settings.store['command_prefix'])):].strip()
            if not in_string:
                return  # empty

            command_list = in_string.split(' ', 1)
            command_name = command_list[0].lower()

            if len(command_list) > 1:
                command_args = command_list[1]
            else:
                command_args = ''

            useraccount = self.bot.accounts.account(event['server'], event['source'])
            if useraccount:
                userlevel = self.bot.accounts.access_level(useraccount)
            else:
                userlevel = USER_LEVEL_NOPRIVS

            called = []
            for module in sorted(self.modules):
                module_commands = self.modules[module].commands
                for search_command in ['*', command_name]:
                    if search_command in module_commands:
                        command_info = module_commands[search_command]
                        if userlevel >= command_info.call_level:
                            # for commands restricted by channel, make and check the priv lists
                            source_chan = event['target'].name
                            source_nick = event['source'].nick

                            # if channel_mode_restriction exists, only allow the command to be run in channels
                            if command_info.channel_mode_restriction and (event['from_to'].is_user or
                                    (event['from_to'].is_channel and not event['from_to'].has_privs(source_nick, lowest_mode=command_info.channel_mode_restriction))):
                                continue

                            current_channel_whitelist = [event['server'].istring(chan) for chan in command_info.channel_whitelist]
                            current_user_whitelist = command_info.user_whitelist
                            for chan in current_channel_whitelist:
                                [current_user_whitelist.append(user) for user in event['server'].get_channel_info(chan)['users']]

                            if source_chan in current_channel_whitelist or source_nick in current_user_whitelist or (not current_channel_whitelist):
                                if command_info.call not in called:
                                    called.append(command_info.call)
                                    threading.Thread(target=command_info.call,
                                                     args=(event, command_info,
                                                           UserCommand(command_name, command_args))).start()
                        else:
                            self.bot.gui.put_line('        No Privs')

    def add_command_info(self, module, name):
        info = self.modules[module].events['commands'][name]

        if isinstance(name, tuple):
            self.modules[module].static_commands[name[0]] = Command(info)

            for alias in name[1:]:
                self.modules[module].static_commands[alias] = Command(info, alias=name[0])

        elif isinstance(name, str):
            self.modules[module].static_commands[name] = Command(info)

    def return_admin_command_dict(self, base, info, cmd_class=AdminCommand):
        return self.return_command_dict(base, info, cmd_class=cmd_class)

    def return_command_dict(self, base, info, cmd_class=Command):
        commands = {}

        if callable(info.get('call', None)):
            call = info['call']
        elif 'call' in info:
            call = getattr(self, info['call'])
        else:
            call = base.combined

        if 'description' in info:
            if isinstance(info['description'], str):
                description = [info['description']]
            elif isinstance(info['description'], list):
                description = info['description']
        else:
            description = ''

        call_level = info.get('call_level', USER_LEVEL_NOPRIVS)
        if call_level in user_levels:
            call_level = user_levels[call_level]

        view_level = info.get('view_level', call_level)
        if view_level in user_levels:
            view_level = user_levels[view_level]

        chanmode = info.get('channel_mode_restriction', None)
        channel_whitelist = info.get('channel_whitelist', [])
        bound = info.get('bound', True)

        commands[info['name'][0]] = cmd_class(call=call, description=description, call_level=call_level,
                                            view_level=view_level, channel_whitelist=channel_whitelist,
                                            json=info, bound=bound, base_name=info['name'][0],
                                            channel_mode_restriction=chanmode)

        for command in info['name'][1:]:
            commands[command] = cmd_class(call=call, description=description, call_level=call_level,
                                        view_level=view_level, channel_whitelist=channel_whitelist,
                                        json=info, bound=bound, base_name=info['name'][0],
                                        alias=info['name'][0], channel_mode_restriction=chanmode)

        return commands
