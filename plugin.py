# -*- coding: utf-8 -*-
###
# Copyright (c) 2002-2004, Jeremiah Fincher
# Copyright (c) 2009-2010, James McCoy
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

import os
import time
import re
import sys

import chardet
from io import StringIO
sys.path.append(os.getcwd() + '/plugins/LogsToDB')
from . import channelLogger_model as channellogger_model

from supybot.commands import *
import supybot.conf as conf
import supybot.world as world
import supybot.ircdb as ircdb
import supybot.irclib as irclib
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils
import supybot.schedule as schedule
import supybot.registry as registry
import supybot.callbacks as callbacks
from supybot.i18n import PluginInternationalization, internationalizeDocstring
_ = PluginInternationalization('LogsToDB')

class FakeLog(object):
    def flush(self):
        return
    def close(self):
        return
    def write(self, s):
        return

class LogsToDB(callbacks.Plugin):
    noIgnore = True
    def __init__(self, irc):
        self.__parent = super(LogsToDB, self)
        self.__parent.__init__(irc)
        self.lastMsgs = {}
        self.lastStates = {}
        self.logs = {}
        self.flusher = self.flush
        world.flushers.append(self.flusher)
        self.logViewerDB = channellogger_model.LogviewerDB()
        self.logViewerFile = channellogger_model.LogviewerFile()
        self.currentUsers = 0
        def myEventCaller():
            self.addCount(irc)
        schedule.addPeriodicEvent(myEventCaller, 600, 'mySpamEvent')


    def addCount(self, irc):
        "Periodically check the amount of users in the channel every 10 minutes"
        for chan in list(irc.state.channels.keys()):
            self.logViewerDB.add_count(len(irc.state.channels[chan].users), chan, irc.state.channels[chan].topic)


    def to_unicode_or_bust(self, obj, encoding='utf-8'):
        if isinstance(obj, str):
            if not isinstance(obj, str):
                obj = str(obj, encoding)

        return obj

    def decode(self, bytes):
        try:
            text = bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                text = bytes.decode('iso-8859-1')
            except UnicodeDecodeError:
                text = bytes.decode('cp1252')
        return text

    def encode(self, bytes):
        try:
            text = bytes.encode('utf-8')
        except UnicodeEncodeError:
            try:
                text = bytes.encode('iso-8859-1')
            except UnicodeEncodeError:
                text = bytes.encode('cp1252')
        return text

    def die(self):
        for log in self._logs():
            log.close()
        world.flushers = [x for x in world.flushers if x is not self.flusher]

    def __call__(self, irc, msg):
        try:
            # I don't know why I put this in, but it doesn't work, because it
            # doesn't call doNick or doQuit.
            # if msg.args and irc.isChannel(msg.args[0]):
            self.__parent.__call__(irc, msg)
            if irc in self.lastMsgs:
                if irc not in self.lastStates:
                    self.lastStates[irc] = irc.state.copy()
                self.lastStates[irc].addMsg(irc, self.lastMsgs[irc])
        finally:
            # We must make sure this always gets updated.
            self.lastMsgs[irc] = msg

    def reset(self):
        for log in self._logs():
            log.close()
        self.logs.clear()
        self.lastMsgs.clear()
        self.lastStates.clear()

    def _logs(self):
        for logs in self.logs.values():
            for log in logs.values():
                yield log

    def flush(self):
        self.checkLogNames()
        for log in self._logs():
            try:
                log.flush()
            except ValueError as e:
                if e.args[0] != 'I/O operation on a closed file':
                    self.log.exception('Odd exception:')

    def logNameTimestamp(self, channel):
        format = self.registryValue('filenameTimestamp', channel)
        return time.strftime(format)

    def getLogName(self, channel):
        if self.registryValue('rotateLogs', channel):
            return '%s.%s.log' % (channel, self.logNameTimestamp(channel))
        else:
            return '%s.log' % channel

    def getLogDir(self, irc, channel):
        logDir = conf.supybot.directories.log.dirize(self.name())
        if self.registryValue('directories'):
            if self.registryValue('directories.network'):
                logDir = os.path.join(logDir,  irc.network)
            if self.registryValue('directories.channel'):
                logDir = os.path.join(logDir, channel)
            if self.registryValue('directories.timestamp'):
                format = self.registryValue('directories.timestamp.format')
                timeDir =time.strftime(format)
                logDir = os.path.join(logDir, timeDir)
        if not os.path.exists(logDir):
            os.makedirs(logDir)
        return logDir

    def checkLogNames(self):
        for (irc, logs) in list(self.logs.items()):
            for (channel, log) in list(logs.items()):
                if self.registryValue('rotateLogs', channel):
                    name = self.getLogName(channel)
                    if name != log.name:
                        log.close()
                        del logs[channel]

    def getLog(self, irc, channel):
        self.checkLogNames()
        try:
            logs = self.logs[irc]
        except KeyError:
            logs = ircutils.IrcDict()
            self.logs[irc] = logs
        if channel in logs:
            return logs[channel]
        else:
            try:
                name = self.getLogName(channel)
                logDir = self.getLogDir(irc, channel)
                log = open(os.path.join(logDir, name), 'a')
                logs[channel] = log
                return log
            except IOError:
                self.log.exception('Error opening log:')
                return FakeLog()

    def timestamp(self, log):
        format = conf.supybot.log.timestampFormat()
        if format:
            log.write(time.strftime(format))
            log.write('  ')

    def normalizeChannel(self, irc, channel):
        return ircutils.toLower(channel)

    def doLog(self, irc, channel, s, *args):
        if not self.registryValue('enable', channel):
            return
        s = format(s, *args)
        channel = self.normalizeChannel(irc, channel)
        log = self.getLog(irc, channel)
        if self.registryValue('timestamp', channel):
            self.timestamp(log)
        if self.registryValue('stripFormatting', channel):
            s = ircutils.stripFormatting(s)
        log.write(s)
        if self.registryValue('flushImmediately'):
            log.flush()

    def doPrivmsg(self, irc, msg):
        (recipients, text) = msg.args
        for channel in recipients.split(','):
            if irc.isChannel(channel):
                noLogPrefix = self.registryValue('noLogPrefix', channel)
                cap = ircdb.makeChannelCapability(channel, 'logChannelMessages')
                try:
                    logChannelMessages = ircdb.checkCapability(msg.prefix, cap,
                        ignoreOwner=True)
                except KeyError:
                    logChannelMessages = True
                nick = msg.nick or irc.nick
                if msg.tagged('LogsToDB__relayed'):
                    (nick, text) = text.split(' ', 1)
                    nick = nick[1:-1]
                    msg.args = (recipients, text)
                if (noLogPrefix and text.startswith(noLogPrefix)) or \
                        not logChannelMessages:
                    text = '-= THIS MESSAGE NOT LOGGED =-'
                if ircmsgs.isAction(msg):
                    self.doLog(irc, channel,
                               '* %s %s\n', nick, ircmsgs.unAction(msg))
                else:
                    self.doLog(irc, channel, '<%s> %s\n', nick, text)
                
                message = msg.args[1]
                self.logViewerDB.add_message(msg.nick, msg.prefix, message, channel)
                self.logViewerFile.write_message(msg.nick, message)

    def doNotice(self, irc, msg):
        (recipients, text) = msg.args
        for channel in recipients.split(','):
            if irc.isChannel(channel):
                self.doLog(irc, channel, '-%s- %s\n', msg.nick, text)


    def getcount(self, irc, msg, args):
        """<count>

        Returns a random quote from <channel>.  <channel> is only necessary if
        the message isn't sent in the channel itself.
        """
        # irc.reply(str(len(irc.state.channels["#web"].users)))
        print(irc.state.channels["#web"].topic)

    getcount = wrap(getcount)

    def doNick(self, irc, msg):
        oldNick = msg.nick
        newNick = msg.args[0]
        for (channel, c) in irc.state.channels.items():
            if newNick in c.users:
                self.doLog(irc, channel,
                           '*** %s is now known as %s\n', oldNick, newNick)
    def doJoin(self, irc, msg):
        for channel in msg.args[0].split(','):
            if(self.registryValue('showJoinParts', channel)):
                self.doLog(irc, channel,
                           '*** %s <%s> has joined %s\n',
                           msg.nick, msg.prefix, channel)
                self.logViewerFile.write_join(msg.nick, msg.prefix, channel)

    def doKick(self, irc, msg):
        if len(msg.args) == 3:
            (channel, target, kickmsg) = msg.args
        else:
            (channel, target) = msg.args
            kickmsg = ''

        print(msg)
        if kickmsg:
            self.doLog(irc, channel,
                       '*** %s was kicked by %s (%s)\n',
                       target, msg.nick, kickmsg)
            self.logViewerFile.write_kick(target, msg.nick, channel)
        else:
            self.doLog(irc, channel,
                       '*** %s was kicked by %s\n', target, msg.nick, channel)
            self.logViewerFile.write_kick(target, msg.nick)

    def doPart(self, irc, msg):
        if len(msg.args) > 1:
            reason = " (%s)" % msg.args[1]
        else:
            reason = ""
        for channel in msg.args[0].split(','):
            if(self.registryValue('showJoinParts', channel)):
                self.doLog(irc, channel,
                           '*** %s <%s> has left %s%s\n',
                           msg.nick, msg.prefix, channel, reason)
                self.logViewerDB.add_part(msg.nick, msg.prefix, channel)
                self.logViewerFile.write_part(msg.nick, msg.prefix, channel)

    def doMode(self, irc, msg):
        channel = msg.args[0]
        if irc.isChannel(channel) and msg.args[1:]:
            self.doLog(irc, channel,
                       '*** %s sets mode: %s %s\n',
                       msg.nick or msg.prefix, msg.args[1],
                        ' '.join(msg.args[2:]))
            if (msg.args[1] == '+b'):                
                self.logViewerFile.write_ban(msg.nick, msg.prefix, msg.args[1], ' '.join(msg.args[2:]), channel)
                self.logViewerDB.write_ban(msg.nick, msg.prefix, msg.args[1], ' '.join(msg.args[2:]), channel)
            elif (msg.args[1] == '-b'):
                self.logViewerFile.write_unban(msg.nick, msg.prefix, msg.args[1], ' '.join(msg.args[2:]), channel)
                self.logViewerDB.write_unban(msg.nick, msg.prefix, msg.args[1], ' '.join(msg.args[2:]), channel)


    def doTopic(self, irc, msg):
        if len(msg.args) == 1:
            return # It's an empty TOPIC just to get the current topic.
        channel = msg.args[0]
        self.doLog(irc, channel,
                   '*** %s changes topic to "%s"\n', msg.nick, msg.args[1])

    def doQuit(self, irc, msg):
        if len(msg.args) == 1:
            reason = " (%s)" % msg.args[0]
        else:
            reason = ""
        if not isinstance(irc, irclib.Irc):
            irc = irc.getRealIrc()
        for (channel, chan) in self.lastStates[irc].channels.items():
            if(self.registryValue('showJoinParts', channel)):
                if msg.nick in chan.users:
                    self.doLog(irc, channel,
                               '*** %s <%s> has quit IRC%s\n',
                               msg.nick, msg.prefix, reason)
                    self.logViewerDB.add_quit(msg.nick, msg.prefix, channel)
                    self.logViewerFile.write_quit(msg.nick, msg.prefix, channel)

    def outFilter(self, irc, msg):
        # Gotta catch my own messages *somehow* :)
        # Let's try this little trick...
        if msg.command in ('PRIVMSG', 'NOTICE'):
            # Other messages should be sent back to us.
            m = ircmsgs.IrcMsg(msg=msg, prefix=irc.prefix)
            if msg.tagged('relayedMsg'):
                m.tag('ChannelLogger__relayed')
            self(irc, m)
        return msg


Class = LogsToDB
# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
