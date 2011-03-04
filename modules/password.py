#!/usr/bin/env python
"""
password.py - Goshubot Password Module
Copyright 2011 Daniel Oakley <danneh@danneh.net>

http://danneh.net/maid/
"""

import hashlib
from gbot.modules import Module

class Password(Module):
	
	name = "Password"
	
	def __init__(self):
		self.commands = {
			'change_password' : self.change_password,
		}
	
	def change_password(self, line, connection, event):
		try:
			(current_pass, new_pass) = line.split(' ')
		except:
			connection.privmsg(event.source().split('!')[0], 'PASSWORD SYNTAX: .pass <current password> <new password>')
			return
		
		if hashlib.sha512(current_pass).hexdigest() == self.gbot.password.hexdigest():
			del self.gbot.password
			self.gbot.password = hashlib.sha512(new_pass)
			connection.privmsg(event.source().split('!')[0], 'PASSWORD: Password Updated')
		else:
			connection.privmsg(event.source().split('!')[0], 'PASSWORD: Password Incorrect')
