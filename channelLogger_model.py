#!/usr/bin/python
import sys
import json
import os
import string
import time
import psycopg2
import logging
import logging.handlers
import re

class LogviewerDB:

	def __init__(self):
		# Will only work on UNIX
		if (hasattr(time, 'tzset')):
			os.environ['TZ'] = 'Europe/London'
			time.tzset()
		fh = logging.handlers.TimedRotatingFileHandler('combined.log', when='midnight', interval=1, backupCount=5);
		logging.basicConfig(level=logging.DEBUG, handlers=[fh], format="%(levelname)s: %(asctime)s -  %(message)s")
		self.__connect()

	def __connect(self):
		logging.debug("Attempting to connect with database...")
		# DB connection string
		try:
			with open('plugins/LogsToDB/config.json') as data:
				config = json.load(data)

			conn_string = "host='%s' dbname='%s' user='%s' password='%s'" % (config['db']['host'], config['db']['dbname'], config['db']['user'], config['db']['password'])
		except IOError as e:
			print(os.getcwd())
			logging.error("Error! No config file supplied, please create a config.json file in the root")
			sys.exit("Error! No config file supplied, please create a config.json file in the root")
		
		# Print connection string
		print("Connecting to database\n -> %s" % (conn_string))
		
		# get a connection
		conn = psycopg2.connect(conn_string)
		
		# conn.curser will return a cursor object, you can use this to perform queries
		self.cursor = conn.cursor()
		self.conn = conn
		logging.debug("connected!")

	def add_count(self, count, channel, topic):
		count = str(count)
		topic = str(topic)
		channel_id = self.get_channel_id(channel)
		try:
			self.cursor.execute("INSERT INTO user_count (count, channel_id, topic) VALUES (%s, %s, %s)", (count, channel_id, topic))
			self.conn.commit()
		except psycopg2.InterfaceError as e:
			logging.error('Error within add_count: ' + e.message)
			logging.debug('Attempting to reconnect with database...')
			self.__connect()

	def add_message(self, user, host, msg, channel):
		self.__add_message(user, host, msg, 'message', channel)

	def add_join(self, user, host, channel):
		self.__add_message(user, host, '', 'join', channel)

	def add_part(self, user, host, channel):
		self.__add_message(user, host, '', 'part', channel)

	def add_quit(self, user, host, channel):
		self.__add_message(user, host, '', 'quit', channel)

	def add_emote(self, user, host, msg, channel):
		self.__add_message(user, host, msg, 'emote', channel)


	def __add_message(self, user, host, msg, action, channel):

		try:
			# Was this message from a user we already have in our database?
			# If so return the userID.
			userID = self.check_user_host_exists(user, host) or False

			# If userID is False, store the new combo then get back the userID
			if not userID:
				self.cursor.execute("INSERT INTO users (\"user\", \"host\") VALUES (%s, %s)", (user, host))
				self.conn.commit()
				# We should now have an ID for our new user/host combo
				userID = self.check_user_host_exists(user, host);

			# check channel exists, if not get_channel_id will generate an ID
			channel_id = self.get_channel_id(channel)

			if (action == 'message' or action == 'emote'):	
				self.cursor.execute("INSERT INTO messages (\"user\", \"content\", \"action\", \"channel_id\") VALUES (%s, %s, %s, %s)", (userID, msg, action, channel_id))
			else:
				self.cursor.execute("INSERT INTO messages (\"user\", \"action\", \"channel_id\") VALUES (%s, %s, %s)", (userID, action, channel_id))
			self.conn.commit()
		except psycopg2.InterfaceError as e:
			logging.error('Error within add_message: ' + e.message)
			logging.debug('Attempting to reconnect with database...')
			self.__connect()			

	def write_ban(self, nick, host, mode, target, channel):
		try:
			# check channel exists, if not get_channel_id will generate an ID
			channel_id = self.get_channel_id(channel)
			# Sometimes users can be kicked to another channel because of join/quit floos, make sure we strip of the ban forwarding
			
			if (len(re.split(r'(\$#.*)', target)) > 1):
				banmask = re.split(r'(\$#.*)', target)[0]
				forwarded_channel = re.sub('^\$', '', re.split(r'(\$#.*)', target)[1])
				self.cursor.execute("INSERT INTO bans (banmask, banned_by, channel, reason) values (%s, %s, %s, %s)", (banmask, nick, channel_id, "Join/Quit flood, user forwarded to " + forwarded_channel))
			else:
				banmask = re.split(r'(\$#.*)', target)[0]
				self.cursor.execute("INSERT INTO bans (banmask, banned_by, channel) values (%s, %s, %s)", (banmask, nick, channel_id))
			self.conn.commit()
		except psycopg2.InterfaceError as e:
			logging.error('Error within write_ban: ' + e.message)
			logging.debug('Attempting to reconnect with database...')
			self.__connect()

	def write_unban(self, nick, host, mode, target, channel):
		try:
			# check channel exists, if not get_channel_id will generate an ID
			channel_id = self.get_channel_id(channel)
			self.cursor.execute("UPDATE bans SET still_banned = FALSE WHERE channel = %s AND banmask = %s", (channel_id, target))
			self.conn.commit()
		except psycopg2.InterfaceError as e:
			logging.error('Error within write_unban: ' + e.message)
			logging.debug('Attempting to reconnect with database...')
			self.__connect()

	# UTILITY FUNCTIONS

	# Check if user exists then return the user ID, if not return false
	def check_user_host_exists(self, user, host):
		try:
			self.cursor.execute("SELECT * FROM users WHERE \"user\"= %s AND \"host\"= %s", (user, host))
			if self.cursor.rowcount:
				return self.cursor.fetchone()[0]
			else:
				return False
		except psycopg2.InterfaceError as e:
			logging.error('Error within check_user_host_exists: ' + e.message)
			logging.debug('Attempting to reconnect with database...')
			self.__connect()


	def get_channel_id(self, channel):
		try:
			self.cursor.execute("SELECT id FROM channels WHERE channel_name = %s", (channel,))
			if self.cursor.rowcount:
				return self.cursor.fetchone()[0]
			else:
				self.cursor.execute("INSERT INTO channels (channel_name) VALUES (%s)", (channel,))
				self.conn.commit()
				return self.get_channel_id(channel)
		except psycopg2.InterfaceError as e:
			logging.error('Error within get_channel_id: ' + e.message)
			logging.debug('Attempting to reconnect with database...')
			self.__connect()

	# Probably don't need this actually
	def get_banned_row_id(self, banmask):
		try:
			self.cursor.execute("SELECT id FROM bans WHERE banmask = %s", (banmask,))
			if self.cursor.rowcount:
				return self.cursor.fetchone()[0]

			return False
		except psycopg2.InterfaceError as e:
			logging.error('Error within get_banned_row_id: ' + e.message)
			logging.debug('Attempting to reconnect with database...')
			self.__connect()


class LogviewerFile:

	def __init__(self):
		# Get Logfile Path
		try:
			with open('plugins/LogsToDB/config.json') as data:
				config = json.load(data)

			self.logPath = config['logs']['folderPath']
		except IOError as e:
			sys.exit("Error! No config file supplied, please create a config.json file in the root")

		# self.all_bytes = string.maketrans('', '')

	def write_message(self, user, msg):
		time_stamp = time.strftime("%H:%M:%S")
		dateStamp = time.strftime("%Y-%m-%d")
		with open(self.logPath + "/%s.log" % dateStamp, 'a') as logFile:
			msg = "%s <%s> %s\n" % (time_stamp, user, msg)
			logFile.write(msg)

	def write_join(self, user, host, channel):
		time_stamp = time.strftime("%H:%M:%S")
		dateStamp = time.strftime("%Y-%m-%d")
		with open(self.logPath + "/%s.log" % dateStamp, 'a') as logFile:
			msg = "%s --> <%s> (%s) joins %s \n" % (time_stamp, user, host, channel)
			logFile.write(msg)

	def write_part(self, user, host, channel):
		time_stamp = time.strftime("%H:%M:%S")
		dateStamp = time.strftime("%Y-%m-%d")
		with open(self.logPath + "/%s.log" % dateStamp, 'a') as logFile:
			msg = "%s <-- <%s> (%s) parts %s \n" % (time_stamp, user, host, channel)
			logFile.write(msg)

	def write_quit(self, user, host, channel):
		time_stamp = time.strftime("%H:%M:%S")
		dateStamp = time.strftime("%Y-%m-%d")
		with open(self.logPath + "/%s.log" % dateStamp, 'a') as logFile:
			msg = "%s <-- <%s> (%s) quits %s \n" % (time_stamp, user, host, channel)
			logFile.write(msg)

	def write_kick(self, target, nick, channel):
		time_stamp = time.strftime("%H:%M:%S")
		dateStamp = time.strftime("%Y-%m-%d")
		with open(self.logPath + "/%s.log" % dateStamp, 'a') as logFile:
			msg = "%s %s has kicked %s from %s \n" % (time_stamp, nick, target, channel)
			logFile.write(msg)

	def write_ban(self, nick, host, mode, target, channel):
		time_stamp = time.strftime("%H:%M:%S")
		dateStamp = time.strftime("%Y-%m-%d")
		with open(self.logPath + "/%s.log" % dateStamp, 'a') as logFile:
			msg = '%s %s sets mode: %s %s\n' % (time_stamp, nick, mode, target)
			logFile.write(msg)

	def write_unban(self, nick, host, mode, target, channel):
		time_stamp = time.strftime("%H:%M:%S")
		dateStamp = time.strftime("%Y-%m-%d")
		with open(self.logPath + "/%s.log" % dateStamp, 'a') as logFile:
			msg = '%s %s sets mode: %s %s\n' % (time_stamp, nick, mode, target)
			logFile.write(msg)
