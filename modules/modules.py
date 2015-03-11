#!/usr/bin/env python3
# Goshubot IRC Bot
# written by Daniel Oaks <daniel@danieloaks.net>
# licensed under the BSD 2-clause license

from gbot.modules import Module
from gbot.users import USER_LEVEL_ADMIN

class modules(Module):
    """Handles loading and unloading modules and their internal JSON dicts"""
    core = True

    def cmd_json(self, event, command, usercommand):
        """Reload all of our, or the given module's, internal JSON dicts

        @usage reload [name]
        @call_level admin
        """
        if not usercommand.arguments:
            return

        do = usercommand.arguments.split()[0].lower()

        if do == 'reload':
            if len(usercommand.arguments.split()) < 2:
                self.bot.irc.msg(event, "Reloading @ball@b modules' JSON dicts")
                modules = True
            else:
                modules = usercommand.arguments.lower().split(' ', 1)[1].split()

            reloaded_module_names = []
            for module_name in self.bot.modules.modules:
                if modules is True or module_name in modules:
                    reloaded_module_names.append(module_name)
                    self.bot.modules.modules[module_name].reload_json()

            self.bot.irc.msg(event, 'Reloaded JSON dicts for modules: {}'.format(', '.join(sorted(reloaded_module_names))))

    def cmd_module(self, event, command, usercommand):
        """Load/Unload/Reload module specified by <name>
        @usage load/unload/reload [name]

        @description List loaded modules
        @usage list

        @call_level admin
        """
        if not usercommand.arguments:
            return

        do = usercommand.arguments.split()[0].lower()

        if do == 'list':
            response = 'Loaded modules: ' + ', '.join(sorted(list(self.bot.modules.whole_modules.keys())))
            self.bot.irc.msg(event, response)
            additional_modules = []
            for path in self.bot.modules.paths:
                modules = self.bot.modules.modules_from_path(path)
                for module in modules:
                    if module not in self.bot.modules.whole_modules:
                        additional_modules.append(module)
            if len(additional_modules) > 0:
                response = 'Additional avaliable modules: ' + ', '.join(sorted(additional_modules))
                self.bot.irc.msg(event, response)

        elif do in ['load', 'unload', 'reload']:
            if len(usercommand.arguments.split()) < 2:
                return
            modules = usercommand.arguments.split(' ', 1)[1].split()
            succeed = []
            fail = []
            for module in modules:
                if do == 'load':
                    worked = self.bot.modules.load(module)
                elif do == 'unload':
                    worked = self.bot.modules.unload(module)
                else:  # reload
                    if self.bot.modules.unload(module):
                        worked = self.bot.modules.load(module)
                    else:
                        worked = False
                if worked:
                    succeed.append(module)
                else:
                    fail.append(module)
            action = do[0].upper() + do[1:]
            if succeed:
                self.bot.irc.msg(event, action + 'ed: ' + ', '.join(sorted(succeed)))
            if fail:
                self.bot.irc.msg(event, action + ' Failed: ' + ', '.join(sorted(fail)))
