#!/usr/bin/python3

# Copyright (C) 2018, 2019 Lee C. Bussy (@LBussy)

# This file is part of LBussy's BrewPi Script Remix (BrewPi-Script-RMX).
#
# BrewPi Script RMX is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# BrewPi Script RMX is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BrewPi Script RMX. If not, see <https://www.gnu.org/licenses/>.

# These scripts were originally a part of brewpi-script, a part of
# the BrewPi project. Legacy support (for the very popular Arduino
# controller) seems to have been discontinued in favor of new hardware.

# All credit for the original brewpi-script goes to @elcojacobs,
# @m-mcgowan, @rbrady, @steersbob, @glibersat, @Niels-R and I'm sure
# many more contributors around the world. My apologies if I have
# missed anyone; those were the names listed as contributors on the
# Legacy branch.

# See: 'original-license.md' for notes about the original project's
# license and credits. */

# Standard Imports
import _thread
from distutils.version import LooseVersion
import urllib.request, urllib.parse, urllib.error
import traceback
import shutil
from pprint import pprint
import getopt
import os
import socket
import time
import sys
import stat
import pwd
import grp
import serial
import simplejson as json
from configobj import ConfigObj
import temperatureProfile
import programController as programmer
import brewpiJson
from BrewPiUtil import Unbuffered
from BrewPiUtil import logMessage
from BrewPiUtil import logError
import BrewPiUtil as util
import brewpiVersion
import pinList
import expandLogMessage
import BrewPiProcess
from backgroundserial import BackGroundSerial
import BrewConvert

from struct import pack

if sys.version_info < (3, 7):  # Check needed software dependencies
    print("\nSorry, requires Python 3.7+.", file=sys.stderr)
    sys.exit(1)

####  ********************************************************************
####
####  IMPORTANT NOTE:  I don't care if you play with the code, but if
####  you do, please comment out the next lines.  Otherwise I will
####  receive a notice for every mistake you make.
####
####  ********************************************************************

#import sentry_sdk
#sentry_sdk.init("https://5644cfdc9bd24dfbaadea6bc867a8f5b@sentry.io/1803681")

compatibleHwVersion = "0.2.4"

# Change directory to where the script is
os.chdir(os.path.dirname(sys.argv[0]))

# Settings will be read from controller, initialize with same defaults as
# controller. This is mainly to show what's expected. Will all be overwritten
# on the first update from the controller

# Control Settings Dictionary
cs = dict(mode='b', beerSet=20.0, fridgeSet=20.0, heatEstimator=0.2,
          coolEstimator=5)

# Control Constants Dictionary
cc = dict(tempFormat="C", tempSetMin=1.0, tempSetMax=30.0, pidMax=10.0,
          Kp=20.000, Ki=0.600, Kd=-3.000, iMaxErr=0.500, idleRangeH=1.000,
          idleRangeL=-1.000, heatTargetH=0.301, heatTargetL=-0.199,
          coolTargetH=0.199, coolTargetL=-0.301, maxHeatTimeForEst="600",
          maxCoolTimeForEst="1200", fridgeFastFilt="1", fridgeSlowFilt="4",
          fridgeSlopeFilt="3", beerFastFilt="3", beerSlowFilt="5",
          beerSlopeFilt="4", lah=0, hs=0)

# Control Variables Dictionary
cv = dict(beerDiff=0.000, diffIntegral=0.000, beerSlope=0.000, p=0.000,
          i=0.000, d=0.000, estPeak=0.000, negPeakEst=0.000,
          posPeakEst=0.000, negPeak=0.000, posPeak=0.000)

# listState = "", "d", "h", "dh" to reflect whether the list is up to date for
# installed (d) and available (h)
deviceList = dict(listState="", installed=[], available=[])

# Read in command line arguments
try:
    opts, args = getopt.getopt(sys.argv[1:], "hc:sqkfld", ['help', 'config=',
                                                           'status', 'quit', 'kill', 'force', 'log', 'dontrunfile',
                                                           'checkstartuponly'])
except getopt.GetoptError:
    print("Unknown parameter, available Options: --help, --config <path to config file>,\n",
          "                                      --status, --quit, --kill, --force, --log,\n",
          "                                      --dontrunfile", file=sys.stderr)
    sys.exit(1)

configFile = None
checkDontRunFile = False
checkStartupOnly = False
logToFiles = False


for o, a in opts:
    # Print help message for command line options
    if o in ('-h', '--help'):
        print("\nAvailable command line options:\n",
              "  --help: Print this help message\n",
              "  --config <path to config file>: Specify a config file to use. When omitted\n",
              "                                  settings/config.cf is used\n",
              "  --status: Check which scripts are already running\n",
              "  --quit: Ask all instances of BrewPi to quit by sending a message to\n",
              "          their socket\n",
              "  --kill: Kill all instances of BrewPi by sending SIGKILL\n",
              "  --force: Force quit/kill conflicting instances of BrewPi and keep this one\n",
              "  --log: Redirect stderr and stdout to log files\n",
              "  --dontrunfile: Check do_not_run_brewpi in www directory and quit if it exists\n",
              "  --checkstartuponly: Exit after startup checks, return 0 if startup is allowed", file=sys.stderr)
        sys.exit(0)
    # Supply a config file
    if o in ('-c', '--config'):
        configFile = os.path.abspath(a)
        if not os.path.exists(configFile):
            print('ERROR: Config file {0} was not found.'.format(configFile), file=sys.stderr)
            sys.exit(1)
    # Send quit instruction to all running instances of BrewPi
    if o in ('-s', '--status'):
        allProcesses = BrewPiProcess.BrewPiProcesses()
        allProcesses.update()
        running = allProcesses.as_dict()
        if running:
            pprint(running)
        else:
            print("No BrewPi scripts running.", file=sys.stderr)
        sys.exit(0)
    # Quit/kill running instances, then keep this one
    if o in ('-q', '--quit'):
        logMessage("Asking all BrewPi processes to quit on their socket.")
        allProcesses = BrewPiProcess.BrewPiProcesses()
        allProcesses.quitAll()
        time.sleep(2)
        sys.exit(0)
    # Send SIGKILL to all running instances of BrewPi
    if o in ('-k', '--kill'):
        logMessage("Killing all BrewPi processes.")
        allProcesses = BrewPiProcess.BrewPiProcesses()
        allProcesses.killAll()
        sys.exit(0)
    # Close all existing instances of BrewPi by quit/kill and keep this one
    if o in ('-f', '--force'):
        logMessage(
            "Closing all existing processes of BrewPi and keeping this one.")
        allProcesses = BrewPiProcess.BrewPiProcesses()
        if len(allProcesses.update()) > 1:  # if I am not the only one running
            allProcesses.quitAll()
            time.sleep(2)
            if len(allProcesses.update()) > 1:
                print("Asking the other processes to quit did not work. Forcing them now.", file=sys.stderr)
    # Redirect output of stderr and stdout to files in log directory
    if o in ('-l', '--log'):
        logToFiles = True
    # Only start brewpi when the dontrunfile is not found
    if o in ('-d', '--dontrunfile'):
        checkDontRunFile = True
    if o in ('-k', '--checkstartuponly'):
        checkStartupOnly = True

if not configFile:
    configFile = '{0}settings/config.cfg'.format(util.addSlash(sys.path[0]))
config = util.readCfgWithDefaults(configFile)

dontRunFilePath = '{0}do_not_run_brewpi'.format(
    util.addSlash(config['wwwPath']))

# Check dont run file when it exists and exit it it does
if checkDontRunFile:
    if os.path.exists(dontRunFilePath):
        # Do not print anything or it will flood the logs
        sys.exit(1)
else:
    # This is here to exit with the semaphore anyway, but print notice
    # This should only be hit when running interactively.
    if os.path.exists(dontRunFilePath):
        print("Semaphore exists, exiting.")
        sys.exit(1)

# Check for other running instances of BrewPi that will cause conflicts with
# this instance
allProcesses = BrewPiProcess.BrewPiProcesses()
allProcesses.update()
myProcess = allProcesses.me()
if allProcesses.findConflicts(myProcess):
    if not checkDontRunFile:
        logMessage("A conflicting BrewPi is running. This instance will exit.")
    sys.exit(1)

if checkStartupOnly:
    sys.exit(0)

localJsonFileName = ""
localCsvFileName = ""
wwwJsonFileName = ""
wwwCsvFileName = ""
lastDay = ""
day = ""

if logToFiles:
    logPath = '{0}logs/'.format(util.addSlash(util.scriptPath()))
    # Skip logging for this message
    print("Logging to {0}.".format(logPath))
    print("Output will not be shown in console.")
    # Append stderr, unbuffered
    sys.stderr = Unbuffered(open(logPath + 'stderr.txt', 'w'))
    # Overwrite stdout, unbuffered
    sys.stdout = Unbuffered(open(logPath + 'stdout.txt', 'w'))


# Get www json setting with default
def getWwwSetting(settingName):
    setting = None
    wwwPath = util.addSlash(config['wwwPath'])
    userSettings = '{0}userSettings.json'.format(wwwPath)
    defaultSettings = '{0}defaultSettings.json'.format(wwwPath)
    try:
        json_file = open(userSettings, 'r')
        data = json.load(json_file)
        # If settingName exists, get value
        if checkKey(data, settingName):
            setting = data[settingName]
        json_file.close()
    except:
        # userSettings.json does not exist
        try:
            json_file = open(defaultSettings, 'r')
            data = json.load(json_file)
            # If settingName exists, get value
            if checkKey(data, settingName):
                setting = data[settingName]
            json_file.close()
        except:
            # defaultSettings.json does not exist, use None
            pass
    return setting


# Check to see if a key exists in a dictionary
def checkKey(dict, key):
    if key in list(dict.keys()):
        return True
    else:
        return False


def changeWwwSetting(settingName, value):
    # userSettings.json is a copy of some of the settings that are needed by the
    # web server. This allows the web server to load properly, even when the script
    # is not running.
    wwwSettingsFileName = '{0}userSettings.json'.format(
        util.addSlash(config['wwwPath']))
    if os.path.exists(wwwSettingsFileName):
        wwwSettingsFile = open(wwwSettingsFileName, 'r+b')
        try:
            wwwSettings = json.load(wwwSettingsFile)  # read existing settings
        except json.JSONDecodeError:
            logMessage(
                "Error while decoding userSettings.json, creating new empty json file.")
            # Start with a fresh file when the json is corrupt.
            wwwSettings = {}
    else:
        wwwSettingsFile = open(wwwSettingsFileName, 'w+b')  # Create new file
        wwwSettings = {}

    try:
        wwwSettings[settingName] = str(value)
        wwwSettingsFile.seek(0)
        wwwSettingsFile.write(json.dumps(wwwSettings).encode(encoding="cp437"))
        wwwSettingsFile.truncate()
        wwwSettingsFile.close()
    except:
        logError("Ran into an error writing the WWW JSON file.")


def setFiles():
    global config
    global localJsonFileName
    global localCsvFileName
    global wwwJsonFileName
    global wwwCsvFileName
    global lastDay
    global day

    # Concatenate directory names for the data
    beerFileName = config['beerName']
    dataPath = '{0}data/{1}/'.format(
        util.addSlash(util.scriptPath()), beerFileName)
    wwwDataPath = '{0}data/{1}/'.format(
        util.addSlash(config['wwwPath']), beerFileName)

    # Create path and set owner and perms (recursively) on directories and files
    owner = 'brewpi'
    group = 'brewpi'
    uid = pwd.getpwnam(owner).pw_uid  # Get UID
    gid = grp.getgrnam(group).gr_gid  # Get GID
    fileMode = stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH | stat.S_IROTH  # 664
    dirMode = stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH | stat.S_IROTH | stat.S_IXOTH  # 775
    if not os.path.exists(dataPath):
        os.makedirs(dataPath) # Create path if it does not exist
    os.chown(dataPath, uid, gid) # chown root directory
    os.chmod(dataPath, dirMode) # chmod root directory
    for root, dirs, files in os.walk(dataPath):
        for dir in dirs:
            os.chown(os.path.join(root, dir), uid, gid) # chown directories
            os.chmod(dir, dirMode) # chmod directories
        for file in files:
            if os.path.isfile(file):
                os.chown(os.path.join(root, file), uid, gid)  # chown files
                os.chmod(file, fileMode)  # chmod files

    # Create path and set owner and perms (recursively) on directories and files
    owner = 'brewpi'
    group = 'www-data'
    uid = pwd.getpwnam(owner).pw_uid  # Get UID
    gid = grp.getgrnam(group).gr_gid  # Get GID
    fileMode = stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH | stat.S_IROTH  # 664
    dirMode = stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH | stat.S_IROTH | stat.S_IXOTH  # 775
    if not os.path.exists(wwwDataPath):
        os.makedirs(wwwDataPath) # Create path if it does not exist
    os.chown(wwwDataPath, uid, gid) # chown root directory
    os.chmod(wwwDataPath, dirMode) # chmod root directory
    for root, dirs, files in os.walk(wwwDataPath):
        for dir in dirs:
            os.chown(os.path.join(root, dir), uid, gid) # chown directories
            os.chmod(dir, dirMode) # chmod directories
        for file in files:
            if os.path.isfile(file):
                os.chown(os.path.join(root, file), uid, gid)  # chown files
                os.chmod(file, fileMode)  # chmod files

    # Keep track of day and make new data file for each day
    day = time.strftime("%Y%m%d")
    lastDay = day
    # Define a JSON file to store the data
    jsonFileName = '{0}-{1}'.format(beerFileName, day)

    # If a file for today already existed, add suffix
    if os.path.isfile('{0}{1}.json'.format(dataPath, jsonFileName)):
        i = 1
        while os.path.isfile('{0}{1}-{2}.json'.format(dataPath, jsonFileName, str(i))):
            i += 1
        jsonFileName = '{0}-{1}'.format(jsonFileName, str(i))

    localJsonFileName = '{0}{1}.json'.format(dataPath, jsonFileName)

    # Handle if we are runing Tilt or iSpindel
    if checkKey(config, 'tiltColor'):
        brewpiJson.newEmptyFile(localJsonFileName, config['tiltColor'], None)
    elif checkKey(config, 'iSpindel'):
        brewpiJson.newEmptyFile(localJsonFileName, None, config['iSpindel'])
    else:
        brewpiJson.newEmptyFile(localJsonFileName, None, None)

    # Define a location on the web server to copy the file to after it is written
    wwwJsonFileName = wwwDataPath + jsonFileName + '.json'

    # Define a CSV file to store the data as CSV (might be useful one day)
    localCsvFileName = (dataPath + beerFileName + '.csv')
    wwwCsvFileName = (wwwDataPath + beerFileName + '.csv')


def startBeer(beerName):
    if config['dataLogging'] == 'active':
        setFiles()
    changeWwwSetting('beerName', beerName)


def startNewBrew(newName):
    global config
    if len(newName) > 1:
        config = util.configSet(configFile, 'beerName', newName)
        config = util.configSet(configFile, 'dataLogging', 'active')
        startBeer(newName)
        logMessage("Restarted logging for beer '%s'." % newName)
        return {'status': 0, 'statusMessage': "Successfully switched to new brew '%s'. " % urllib.parse.unquote(newName) +
                                              "Please reload the page."}
    else:
        return {'status': 1, 'statusMessage': "Invalid new brew name '%s', please enter\n" +
                                              "a name with at least 2 characters" % urllib.parse.unquote(newName)}


def stopLogging():
    global config
    logMessage("Stopped data logging temp control continues.")
    config = util.configSet(configFile, 'beerName', None)
    config = util.configSet(configFile, 'dataLogging', 'stopped')
    changeWwwSetting('beerName', None)
    return {'status': 0, 'statusMessage': "Successfully stopped logging."}


def pauseLogging():
    global config
    logMessage("Paused logging data, temp control continues.")
    if config['dataLogging'] == 'active':
        config = util.configSet(configFile, 'dataLogging', 'paused')
        return {'status': 0, 'statusMessage': "Successfully paused logging."}
    else:
        return {'status': 1, 'statusMessage': "Logging already paused or stopped."}


def resumeLogging():
    global config
    logMessage("Continued logging data.")
    if config['dataLogging'] == 'paused':
        config = util.configSet(configFile, 'dataLogging', 'active')
        return {'status': 0, 'statusMessage': "Successfully continued logging."}
    else:
        return {'status': 1, 'statusMessage': "Logging was not paused."}


def checkBluetooth(interface = 0):
    sock = None
    try:
        sock = socket.socket(family = socket.AF_BLUETOOTH,
                             type = socket.SOCK_RAW,
                             proto = socket.BTPROTO_HCI)
        sock.setblocking(False)
        sock.setsockopt(socket.SOL_HCI, socket.HCI_FILTER, pack("IIIh2x", 0xffffffff,0xffffffff,0xffffffff,0))
        sock.bind((interface,))
    except:
        if sock is not None:
            sock.close()
        return False
    else:
        return True

# Bytes are read from nonblocking serial into this buffer and processed when
# the buffer contains a full line.
ser = util.setupSerial(config)
if not ser:
    sys.exit(1)

prevTempJson = {}
thread = False
threads = []
tilt = None
tiltbridge = False


# Initialize prevTempJson with base values:
if not prevTempJson:
    prevTempJson = {
        'BeerTemp': 0,
        'FridgeTemp': 0,
        'BeerAnn': None,
        'FridgeAnn': None,
        'RoomTemp': None,
        'State': None,
        'BeerSet': 0,
        'FridgeSet': 0}

# Initialize Tilt and start monitoring
if checkKey(config, 'tiltColor') and config['tiltColor'] != "":
    if not checkBluetooth():
        logError("Configured for Tilt but no Bluetooth radio available.")
    else:
        import Tilt
        tilt = Tilt.TiltManager(config['tiltColor'], 300, 10000, 0)
        tilt.loadSettings()
        tilt.start()
        # Create prevTempJson for Tilt
        prevTempJson.update({
            config['tiltColor'] + 'Temp': 0,
            config['tiltColor'] + 'SG': 0,
            config['tiltColor'] + 'Batt': 0
        })

# Initialise iSpindel and start monitoring
ispindel = None
if checkKey(config, 'iSpindel') and config['iSpindel'] != "":
    ispindel = True
    # Create prevTempJson for iSpindel
    prevTempJson.update({
        'spinSG': 0,
        'spinBatt': 0,
        'spinTemp': 0
    })


# Start the logs
logError('Starting BrewPi.')  # Timestamp stderr
if logToFiles:
    # Make sure we send a message to daemon
    print('Starting BrewPi.', file=sys.__stdout__)
else:
    logMessage('Starting BrewPi.')

# Output the current script version
version = os.popen(
    'git describe --tags $(git rev-list --tags --max-count=1)').read().strip()
branch = os.popen('git branch | grep \* | cut -d " " -f2').read().strip()
commit = os.popen('git -C . log --oneline -n1').read().strip()
logMessage('{0} ({1}) [{2}]'.format(version, branch, commit))

lcdText = ['Script starting up.', ' ', ' ', ' ']
statusType = ['N/A', 'N/A', 'N/A', 'N/A']
statusValue = ['N/A', 'N/A', 'N/A', 'N/A']

if config['beerName'] == 'None':
    logMessage("Logging is stopped.")
else:
    logMessage("Starting '" +
        urllib.parse.unquote(config['beerName']) + ".'")

logMessage("Waiting 10 seconds for board to restart.")
# Wait for 10 seconds to allow an Uno to reboot
time.sleep(float(config.get('startupDelay', 10)))

logMessage("Checking software version on controller.")
hwVersion = brewpiVersion.getVersionFromSerial(ser)
if hwVersion is None:
    logMessage("ERROR: Cannot receive version number from controller.")
    logMessage("Your controller is either not programmed or running a")
    logMessage("very old version of BrewPi. Please upload a new version")
    logMessage("of BrewPi to your controller.")
    # Script will continue so you can at least program the controller
    lcdText = ['Could not receive', 'ver from controller',
               'Please (re)program', 'your controller.']
else:
    logMessage("Found " + hwVersion.toExtendedString() +
               " on port " + ser.name + ".")
    if LooseVersion(hwVersion.toString()) < LooseVersion(compatibleHwVersion):
        logMessage("Warning: Minimum BrewPi version compatible with this")
        logMessage("script is {0} but version number received is".format(
            compatibleHwVersion))
        logMessage("{0}.".format(hwVersion.toString()))
    if int(hwVersion.log) != int(expandLogMessage.getVersion()):
        logMessage("Warning: version number of local copy of logMessages.h")
        logMessage("does not match log version number received from")
        logMessage(
            "controller. Controller version = {0}, local copy".format(hwVersion.log))
        logMessage("version = {0}.".format(str(expandLogMessage.getVersion())))

bg_ser = None

if ser is not None:
    ser.flush()
    # Set up background serial processing, which will continuously read data
    # from serial and put whole lines in a queue
    bg_ser = BackGroundSerial(ser)
    bg_ser.start()
    # Request settings from controller, processed later when reply is received
    bg_ser.write('s')  # request control settings cs
    bg_ser.write('c')  # request control constants cc
    bg_ser.write('v')  # request control variables cv
    # Answer from controller is received asynchronously later.

# Create a listening socket to communicate with PHP
is_windows = sys.platform.startswith('win')
useInetSocket = bool(config.get('useInetSocket', is_windows))
if useInetSocket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    socketPort = config.get('socketPort', 6332)
    s.bind((config.get('socketHost', 'localhost'), int(socketPort)))
    logMessage('Bound to TCP socket on port %d ' % int(socketPort))
else:
    socketFile = util.addSlash(util.scriptPath()) + 'BEERSOCKET'
    if os.path.exists(socketFile):
        # If socket already exists, remove it
        os.remove(socketFile)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(socketFile)  # Bind BEERSOCKET
    # Set owner and permissions for socket
    fileMode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP  # 660
    owner = 'brewpi'
    group = 'www-data'
    uid = pwd.getpwnam(owner).pw_uid
    gid = grp.getgrnam(group).gr_gid
    os.chown(socketFile, uid, gid)  # chown socket
    os.chmod(socketFile, fileMode)  # chmod socket

serialCheckInterval = 0.5
s.setblocking(1)  # Set socket functions to be blocking
s.listen(10)  # Create a backlog queue for up to 10 connections
# Blocking socket functions wait 'serialCheckInterval' seconds
s.settimeout(serialCheckInterval)

prevDataTime = 0  # Keep track of time between new data requests
prevTimeOut = time.time()
prevLcdUpdate = time.time()
prevSettingsUpdate = time.time()

# Timestamps to expire values
lastBbApi = 0
timeoutBB = 300
lastiSpindel = 0
timeoutiSpindel = 1800
lastTiltbridge = 0
timeoutTiltbridge = 300

startBeer(config['beerName'])  # Set up files and prep for run

# Log full JSON if logJson is True in config, none if not set at all,
# else just a ping
outputJson = None
if checkKey(config, 'logJson'):
    if config['logJson'] == 'True':
        outputJson = True
    else:
        outputJson = False


def renameTempKey(key):
    rename = {
        'bt': 'BeerTemp',
        'bs': 'BeerSet',
        'ba': 'BeerAnn',
        'ft': 'FridgeTemp',
        'fs': 'FridgeSet',
        'fa': 'FridgeAnn',
        'rt': 'RoomTemp',
        's':  'State',
        't':  'Time',
        'tg': 'TiltSG',
        'tt': 'TiltTemp',
        'tb': 'TiltBatt',
        'sg': 'spinSG',
        'st': 'spinTemp',
        'sb': 'spinBatt'}
    return rename.get(key, key)


# Allow script loop to run
run = 1

try:
    while run:
        bc = BrewConvert.BrewConvert()
        if config['dataLogging'] == 'active':
            # Check whether it is a new day
            lastDay = day
            day = time.strftime("%Y%m%d")
            if lastDay != day:
                logMessage("New day, creating new JSON file.")
                setFiles()

        if os.path.exists(dontRunFilePath):
            # Allow stopping script via semaphore
            logMessage("Semaphore detected, exiting.")
            run = 0

        # Wait for incoming socket connections.
        # When nothing is received, socket.timeout will be raised after
        # serialCheckInterval seconds. Serial receive will be done then.
        # When messages are expected on serial, the timeout is raised 'manually'

        try:  # Process socket messages
            conn, addr = s.accept()
            conn.setblocking(1)

            # Blocking receive, times out in serialCheckInterval
            message = conn.recv(4096).decode(encoding="cp437")

            if "=" in message: # Split to message/value if message has an '='
                messageType, value = message.split("=", 1)
            else:
                messageType = message
                value = ""

            if messageType == "ack": # Acknowledge request
                conn.send('ack')
            elif messageType == "lcd": # LCD contents requested
                conn.send(json.dumps(lcdText).encode(encoding="cp437"))
            elif messageType == "getMode": # Echo mode setting
                conn.send(cs['mode'])
            elif messageType == "getFridge": # Echo fridge temperature setting
                conn.send(json.dumps(cs['fridgeSet']).encode('utf-8'))
            elif messageType == "getBeer": # Echo beer temperature setting
                conn.send(json.dumps(cs['beerSet']).encode('utf-8'))
            elif messageType == "getControlConstants": # Echo control constants
                conn.send(json.dumps(cc).encode('utf-8'))
            elif messageType == "getControlSettings": # Echo control settings
                if cs['mode'] == "p":
                    profileFile = util.addSlash(
                        util.scriptPath()) + 'settings/tempProfile.csv'
                    with open(profileFile, 'r') as prof:
                        cs['profile'] = prof.readline().split(",")[-1].rstrip("\n")
                cs['dataLogging'] = config['dataLogging']
                conn.send(json.dumps(cs).encode('utf-8'))
            elif messageType == "getControlVariables": # Echo control variables
                conn.send(json.dumps(cv).encode('utf-8'))
            elif messageType == "refreshControlConstants": # Request control constants from controller
                bg_ser.write("c")
                raise socket.timeout
            elif messageType == "refreshControlSettings":  # Request control settings from controller
                bg_ser.write("s")
                raise socket.timeout
            elif messageType == "refreshControlVariables":  # Request control variables from controller
                bg_ser.write("v")
                raise socket.timeout
            elif messageType == "loadDefaultControlSettings":
                bg_ser.write("S")
                raise socket.timeout
            elif messageType == "loadDefaultControlConstants":
                bg_ser.write("C")
                raise socket.timeout
            elif messageType == "setBeer":  # New constant beer temperature received
                try:
                    newTemp = float(value)
                except ValueError:
                    logMessage("Cannot convert temperature '" +
                               value + "' to float.")
                    continue
                if cc['tempSetMin'] <= newTemp <= cc['tempSetMax']:
                    cs['mode'] = 'b'
                    # Round to 2 dec, python will otherwise produce 6.999999999
                    cs['beerSet'] = round(newTemp, 2)
                    bg_ser.write(
                        "j{mode:b, beerSet:" + json.dumps(cs['beerSet']) + "}")
                    logMessage("Beer temperature set to {0} degrees by web.".format(
                        str(cs['beerSet'])))
                    raise socket.timeout  # Go to serial communication to update controller
                else:
                    logMessage(
                        "Beer temperature setting {0} is outside of allowed".format(str(newTemp)))
                    logMessage("range {0} - {1}. These limits can be changed in".format(
                        str(cc['tempSetMin']), str(cc['tempSetMax'])))
                    logMessage("advanced settings.")
            elif messageType == "setFridge":  # New constant fridge temperature received
                try:
                    newTemp = float(value)
                except ValueError:
                    logMessage(
                        "Cannot convert temperature '{0}' to float.".format(value))
                    continue
                if cc['tempSetMin'] <= newTemp <= cc['tempSetMax']:
                    cs['mode'] = 'f'
                    cs['fridgeSet'] = round(newTemp, 2)
                    bg_ser.write("j{mode:f, fridgeSet:" +
                                 json.dumps(cs['fridgeSet']) + "}")
                    logMessage("Fridge temperature set to {0} degrees by web.".format(
                        str(cs['fridgeSet'])))
                    raise socket.timeout  # Go to serial communication to update controller
                else:
                    logMessage(
                        "Fridge temperature setting {0} is outside of allowed".format(str(newTemp)))
                    logMessage("range {0} - {1}. These limits can be changed in".format(
                        str(cc['tempSetMin']), str(cc['tempSetMax'])))
                    logMessage("advanced settings.")
            elif messageType == "setOff":  # Control mode set to OFF
                cs['mode'] = 'o'
                bg_ser.write("j{mode:o}")
                logMessage("Temperature control disabled.")
                raise socket.timeout
            elif messageType == "setParameters":
                # Receive JSON key:value pairs to set parameters on the controller
                try:
                    decoded = json.loads(value)
                    bg_ser.write("j" + json.dumps(decoded))
                    if 'tempFormat' in decoded:
                        # Change in web interface settings too
                        changeWwwSetting('tempFormat', decoded['tempFormat'])
                except json.JSONDecodeError:
                    logMessage("ERROR: Invalid JSON parameter.  String received:")
                    logMessage(value)
                raise socket.timeout
            elif messageType == "stopScript":  # Exit instruction received. Stop script.
                # Voluntary shutdown.
                logMessage('Stop message received on socket.')
                sys.stdout.flush()
                # Also log stop back to daemon
                if logToFiles:
                    print('Stop message received on socket.', file=sys.__stdout__)
                run = 0
                # Write a file to prevent the daemon from restarting the script
                wwwPath = util.addSlash(config['wwwPath'])
                dontRunFilePath = '{0}do_not_run_brewpi'.format(wwwPath)
                util.createDontRunFile(dontRunFilePath)
            elif messageType == "quit":  # Quit but do not write semaphore
                # Quit instruction received. Probably sent by another brewpi
                # script instance
                logMessage("Quit message received on socket.")
                run = 0
                # Leave dontrunfile alone.
                # This instruction is meant to restart the script or replace
                # it with another instance.
                continue
            elif messageType == "eraseLogs":  # Erase stderr and stdout
                open(util.scriptPath() + '/logs/stderr.txt', 'wb').close()
                open(util.scriptPath() + '/logs/stdout.txt', 'wb').close()
                logMessage("Log files erased.")
                logError("Log files erased.")
                continue
            elif messageType == "interval":  # New interval received
                newInterval = int(value)
                if 5 < newInterval < 5000:
                    try:
                        config = util.configSet(
                            configFile, 'interval', float(newInterval))
                    except ValueError:
                        logMessage(
                            "Cannot convert interval '{0}' to float.".format(value))
                        continue
                    logMessage("Interval changed to {0} seconds.".format(
                        str(newInterval)))
            elif messageType == "startNewBrew":  # New beer name
                newName = value
                result = startNewBrew(newName)
                conn.send(json.dumps(result).encode('utf-8'))
            elif messageType == "pauseLogging":  # Pause logging
                result = pauseLogging()
                conn.send(json.dumps(result).encode('utf-8'))
            elif messageType == "stopLogging":  # Stop logging
                result = stopLogging()
                conn.send(json.dumps(result).encode('utf-8'))
            elif messageType == "resumeLogging":  # Resume logging
                result = resumeLogging()
                conn.send(json.dumps(result).encode('utf-8'))
            elif messageType == "dateTimeFormatDisplay":  # Change date time format
                config = util.configSet(configFile, 'dateTimeFormatDisplay', value)
                changeWwwSetting('dateTimeFormatDisplay', value)
                logMessage("Changing date format config setting: " + value)
            elif messageType == "setActiveProfile":  # Get and process beer profile
                # Copy the profile CSV file to the working directory
                logMessage("Setting profile '%s' as active profile." % value)
                config = util.configSet(configFile, 'profileName', value)
                changeWwwSetting('profileName', value)
                profileSrcFile = util.addSlash(
                    config['wwwPath']) + "data/profiles/" + value + ".csv"
                profileDestFile = util.addSlash(
                    util.scriptPath()) + 'settings/tempProfile.csv'
                profileDestFileOld = profileDestFile + '.old'
                try:
                    if os.path.isfile(profileDestFile):
                        if os.path.isfile(profileDestFileOld):
                            os.remove(profileDestFileOld)
                        os.rename(profileDestFile, profileDestFileOld)
                    shutil.copy(profileSrcFile, profileDestFile)
                    # For now, store profile name in header row (in an additional
                    # column)
                    with open(profileDestFile, 'r') as original:
                        line1 = original.readline().rstrip("\n")
                        rest = original.read()
                    with open(profileDestFile, 'w') as modified:
                        modified.write(line1 + "," + value + "\n" + rest)
                except IOError as e:  # Catch all exceptions and report back an error
                    error = b"I/O Error(%d) updating profile: %s." % (e.errno,
                                                                     e.strerror)
                    conn.send(error)
                    logMessage(error)
                else:
                    conn.send(b"Profile successfully updated.")
                    if cs['mode'] is not 'p':
                        cs['mode'] = 'p'
                        bg_ser.write("j{mode:p}")
                        logMessage("Profile mode enabled.")
                        raise socket.timeout  # Go to serial communication to update controller
            elif messageType == "programController" or messageType == "programArduino":  # Reprogram controller
                if bg_ser is not None:
                    bg_ser.stop()
                if ser is not None:
                    if ser.isOpen():
                        ser.close()  # Close serial port before programming
                    ser = None
                try:
                    programParameters = json.loads(value)
                    hexFile = programParameters['fileName']
                    boardType = programParameters['boardType']
                    restoreSettings = programParameters['restoreSettings']
                    restoreDevices = programParameters['restoreDevices']
                    programmer.programController(config, boardType, hexFile, {
                                                 'settings': restoreSettings, 'devices': restoreDevices})
                    logMessage(
                        "New program uploaded to controller, script will restart.")
                except json.JSONDecodeError:
                    logMessage(
                        "ERROR. Cannot decode programming parameters: " + value)
                    logMessage("Restarting script without programming.")

                # Restart the script when done. This replaces this process with
                # the new one
                time.sleep(5)  # Give the controller time to reboot
                python3 = sys.executable
                os.execl(python3, python3, *sys.argv)
            elif messageType == "refreshDeviceList":  # Request devices from controller
                deviceList['listState'] = ""  # Invalidate local copy
                if value.find("readValues") != -1:
                    bg_ser.write("d{r:1}")  # Request installed devices
                    # Request available, but not installed devices
                    bg_ser.write("h{u:-1,v:1}")
                else:
                    bg_ser.write("d{}")  # Request installed devices
                    # Request available, but not installed devices
                    bg_ser.write("h{u:-1}")
            elif messageType == "getDeviceList":  # Echo device list
                if deviceList['listState'] in ["dh", "hd"]:
                    response = dict(board=hwVersion.board,
                                    shield=hwVersion.shield,
                                    deviceList=deviceList,
                                    pinList=pinList.getPinList(hwVersion.board, hwVersion.shield))
                    conn.send(json.dumps(response).encode('utf-8'))
                else:
                    conn.send("device-list-not-up-to-date")
            elif messageType == "applyDevice":  # Change device settings
                try:
                    # Load as JSON to check syntax
                    configStringJson = json.loads(value)
                except json.JSONDecodeError:
                    logMessage(
                        "ERROR. Invalid JSON parameter string received: {0}".format(value))
                    continue
                bg_ser.write("U{0}".format(json.dumps(configStringJson)))
                deviceList['listState'] = ""  # Invalidate local copy
            elif messageType == "writeDevice":  # Configure a device
                try:
                    # Load as JSON to check syntax
                    configStringJson = json.loads(value)
                except json.JSONDecodeError:
                    logMessage(
                        "ERROR: invalid JSON parameter string received: " + value)
                    continue
                bg_ser.write("d" + json.dumps(configStringJson))
            elif messageType == "getVersion":  # Get firmware version from controller
                if hwVersion:
                    response = hwVersion.__dict__
                    # Replace LooseVersion with string, because it is not
                    # JSON serializable
                    response['version'] = hwVersion.toString()
                else:
                    response = {}
                conn.send(json.dumps(response).encode('utf-8'))
            elif messageType == "resetController":  # Erase EEPROM
                logMessage("Resetting controller to factory defaults.")
                bg_ser.write("E")
            elif messageType == "api":  # External API Received

                # Receive an API message in JSON key:value pairs
                # conn.send("Ok")

                try:
                    api = json.loads(value)

                    if checkKey(api, 'api_key'):
                        apiKey = api['api_key']

                        # BEGIN: Process a Brew Bubbles API POST
                        if apiKey == "Brew Bubbles":  # Received JSON from Brew Bubbles
                            # Log received line if true, false is short message, none = mute
                            if outputJson == True:
                                logMessage("API BB JSON Recvd: " + json.dumps(api))
                            elif outputJson == False:
                                logMessage("API Brew Bubbles JSON received.")
                            else:
                                pass  # Don't log JSON messages

                            # Set time of last update
                            lastBbApi = timestamp = time.time()

                            # Update prevTempJson if keys exist
                            if checkKey(prevTempJson, 'bbbpm'):
                                prevTempJson['bbbpm'] = api['bpm']
                                prevTempJson['bbamb'] = api['ambient']
                                prevTempJson['bbves'] = api['temp']
                            # Else, append values to prevTempJson
                            else:
                                prevTempJson.update({
                                    'bbbpm': api['bpm'],
                                    'bbamb': api['ambient'],
                                    'bbves': api['temp']
                                })
                        # END: Process a Brew Bubbles API POST

                        else:
                            logMessage("WARNING: Unknown API key received in JSON:")
                            logMessage(value)

                    # Begin: iSpindel Processing
                    elif checkKey(api, 'name') and checkKey(api, 'ID') and checkKey(api, 'gravity'): # iSpindel

                        if ispindel is not None and config['iSpindel'] == api['name']:

                            # Log received line if true, false is short message, none = mute
                            if outputJson:
                                logMessage("API iSpindel JSON Recvd: " + json.dumps(api))
                            elif not outputJson:
                                logMessage("API iSpindel JSON received.")
                            else:
                                pass  # Don't log JSON messages

                            # Set time of last update
                            lastiSpindel = timestamp = time.time()

                            # Convert to proper temp unit
                            _temp = 0
                            if cc['tempFormat'] == api['temp_units']:
                                _temp = api['temperature']
                            elif cc['tempFormat'] == 'F':
                                _temp = bc.convert(api['temperature'], 'C', 'F')
                            else:
                                _temp = bc.convert(api['temperature'], 'F', 'C')

                            # Update prevTempJson if keys exist
                            if checkKey(prevTempJson, 'battery'):
                                prevTempJson['spinBatt'] = api['battery']
                                prevTempJson['spinSG'] = api['gravity']
                                prevTempJson['spinTemp'] = _temp

                            # Else, append values to prevTempJson
                            else:
                                prevTempJson.update({
                                    'spinBatt': api['battery'],
                                    'spinSG': api['gravity'],
                                    'spinTemp': _temp
                                })

                        elif not ispindel:
                            logError('iSpindel packet received but no iSpindel configuration exists in {0}settings/config.cfg'.format(
                                util.addSlash(sys.path[0])))

                        else:
                            logError('Received iSpindel packet not matching config in {0}settings/config.cfg'.format(
                                util.addSlash(sys.path[0])))
                    # End: iSpindel Processing

                    # Begin: Tiltbridge Processing
                    elif checkKey(api, 'mdns_id') and checkKey(api, 'tilts'):
                        # Received JSON from Tiltbridge
                        # Log received line if true, false is short message, none = mute
                        if outputJson == True:
                            logMessage("API TB JSON Recvd: " + json.dumps(api))
                        elif outputJson == False:
                            logMessage("API Tiltbridge JSON received.")
                        else:
                            pass  # Don't log JSON messages

                        # Loop through (value) and match config["tiltColor"]
                        for t in api:
                            if t == "tilts":
                                for c in api['tilts']:
                                    if c == config["tiltColor"]:
                                        # Found, turn off regular Tilt
                                        if tiltbridge == False:
                                            logMessage("Turned on Tiltbridge.")
                                            tiltbridge = True
                                            try:
                                               tilt
                                            except NameError:
                                               tilt = None
                                            if tilt is not None:  # If we are running a Tilt, stop it
                                               logMessage("Stopping Tilt.")
                                               tilt.stop()
                                               tilt = None

                                        # Set time of last update
                                        lastTiltbridge = timestamp = time.time()
                                        _temp = api['tilts'][config['tiltColor']]['temp']
                                        if cc['tempFormat'] == 'C':
                                            _temp = round(bc.convert(_temp, 'F', 'C'), 1)
                                        prevTempJson[config["tiltColor"] + 'Temp'] = round(_temp, 1)
                                        prevTempJson[config["tiltColor"] + 'SG'] = float(api['tilts'][config['tiltColor']]['gravity'])
                                        #  TODO:  prevTempJson[config["tiltColor"] + 'Batt'] = api['tilts'][config['tiltColor']]['batt']
                                        prevTempJson[config["tiltColor"] + 'Batt'] = None

                    # END:  Tiltbridge Processing

                    else:
                        logError("Received API message, however no matching configuration exists.")

                except json.JSONDecodeError:
                    logError(
                        "Invalid JSON received from API. String received:")
                    logError(value)
                except Exception as e:
                    logError("Unknown error processing API. String received:")
                    logError(value)

            elif messageType == "statusText":  # Status contents requested
                status = {}
                statusIndex = 0

                # Get any items pending for the status box
                # Javascript will determine what/how to display

                if cc['tempFormat'] == 'C':
                    tempSuffix = "&#x2103;"
                else:
                    tempSuffix = "&#x2109;"

                # Begin: Brew Bubbles Items
                if checkKey(prevTempJson, 'bbbpm'):
                    status[statusIndex] = {}
                    statusType = "Airlock: "
                    statusValue = str(round(prevTempJson['bbbpm'], 1)) + " bpm"
                    status[statusIndex].update({statusType: statusValue})
                    statusIndex = statusIndex + 1
                if checkKey(prevTempJson, 'bbamb'):
                    if not int(prevTempJson['bbamb']) == -100: # filter out disconnected sensors
                        status[statusIndex] = {}
                        statusType= "Ambient Temp: "
                        statusValue = str(round(prevTempJson['bbamb'], 1)) + tempSuffix
                        status[statusIndex].update({statusType: statusValue})
                        statusIndex = statusIndex + 1
                if checkKey(prevTempJson, 'bbves'):
                    if not int(prevTempJson['bbves']) == -100: # filter out disconnected sensors
                        status[statusIndex] = {}
                        statusType = "Vessel Temp: "
                        statusValue = str(round(prevTempJson['bbves'], 1)) + tempSuffix
                        status[statusIndex].update({statusType: statusValue})
                        statusIndex = statusIndex + 1
                # End: Brew Bubbles Items

                # Begin: Tilt Items
                if tilt or tiltbridge:
                    if not config['dataLogging'] == 'active': # Only display SG in status when not logging data
                        if not prevTempJson[config['tiltColor'] + 'Temp'] == 0: # Use as a check to see if it's online
                            if checkKey(prevTempJson, config['tiltColor'] + 'SG'):
                                if prevTempJson[config['tiltColor'] + 'SG'] is not None:
                                    status[statusIndex] = {}
                                    statusType = "Tilt SG: "
                                    statusValue = str(prevTempJson[config['tiltColor'] + 'SG'])
                                    status[statusIndex].update({statusType: statusValue})
                                    statusIndex = statusIndex + 1
                    if checkKey(prevTempJson, config['tiltColor'] + 'Batt'):
                        if prevTempJson[config['tiltColor'] + 'Batt'] is not None:
                            if not prevTempJson[config['tiltColor'] + 'Batt'] == 0:
                                status[statusIndex] = {}
                                statusType = "Tilt Batt Age: "
                                statusValue = str(round(prevTempJson[config['tiltColor'] + 'Batt'], 1)) + " wks"
                                status[statusIndex].update({statusType: statusValue})
                                statusIndex = statusIndex + 1
                    if checkKey(prevTempJson, config['tiltColor'] + 'Temp'): # and (statusIndex <= 3):
                        if prevTempJson[config['tiltColor'] + 'Temp'] is not None:
                            if not prevTempJson[config['tiltColor'] + 'Temp'] == 0:
                                status[statusIndex] = {}
                                statusType = "Tilt Temp: "
                                statusValue = str(round(prevTempJson[config['tiltColor'] + 'Temp'], 1)) + tempSuffix
                                status[statusIndex].update({statusType: statusValue})
                                statusIndex = statusIndex + 1
                # End: Tilt Items

                # Begin: iSpindel Items
                if ispindel is not None:
                    if config['dataLogging'] == 'active': # Only display SG in status when not logging data
                        if checkKey(prevTempJson, 'spinSG'):
                            if prevTempJson['spinSG'] is not None:
                                status[statusIndex] = {}
                                statusType = "iSpindel SG: "
                                statusValue = str(prevTempJson['spinSG'])
                                status[statusIndex].update({statusType: statusValue})
                                statusIndex = statusIndex + 1
                    if checkKey(prevTempJson, 'spinBatt'):
                        if prevTempJson['spinBatt'] is not None:
                            status[statusIndex] = {}
                            statusType = "iSpindel Batt: "
                            statusValue = str(round(prevTempJson['spinBatt'], 1)) + "VDC"
                            status[statusIndex].update({statusType: statusValue})
                            statusIndex = statusIndex + 1
                    if checkKey(prevTempJson, 'spinTemp'):
                        if prevTempJson['spinTemp'] is not None:
                            status[statusIndex] = {}
                            statusType = "iSpindel Temp: "
                            statusValue = str(round(prevTempJson['spinTemp'], 1)) + tempSuffix
                            status[statusIndex].update({statusType: statusValue})
                            statusIndex = statusIndex + 1
                # End: iSpindel Items

                conn.send(json.dumps(status).encode('utf-8'))

            else:  # Invalid message received
                logMessage("ERROR. Received invalid message on socket: " + message)

            if (time.time() - prevTimeOut) < serialCheckInterval:
                continue
            else:  # Raise exception to check serial for data immediately
                raise socket.timeout

        except socket.timeout:  # Do serial communication and update settings every SerialCheckInterval
            prevTimeOut = time.time()

            if hwVersion is None:  # Do nothing if we cannot read version
                # Controller has not been recognized
                continue

            if(time.time() - prevLcdUpdate) > 5:  # Request new LCD value
                prevLcdUpdate += 5  # Give the controller some time to respond
                bg_ser.write('l')

            if(time.time() - prevSettingsUpdate) > 60:  # Request Settings from controller
                # Controller should send updates on changes, this is a periodic
                # update to ensure it is up to date
                prevSettingsUpdate += 5  # Give the controller some time to respond
                bg_ser.write('s')

            # If no new data has been received for serialRequestInteval seconds
            if (time.time() - prevDataTime) >= float(config['interval']):
                if prevDataTime == 0:  # First time through set the previous time
                    prevDataTime = time.time()
                prevDataTime += 5  # Give the controller some time to respond to prevent requesting twice
                bg_ser.write("t")  # Request new from controller
                prevDataTime += 5  # Give the controller some time to respond to prevent requesting twice

            # Controller not responding
            elif (time.time() - prevDataTime) > float(config['interval']) + 2 * float(config['interval']):
                logMessage(
                    "ERROR: Controller is not responding to new data requests.")

            while True:  # Read lines from controller
                line = bg_ser.read_line()
                message = bg_ser.read_message()
                if line is None and message is None:
                    break
                if line is not None:
                    try:
                        if line[0] == 'T':  # Temp info received
                            # Store time of last new data for interval check
                            prevDataTime = time.time()

                            if config['dataLogging'] == 'paused' or config['dataLogging'] == 'stopped':
                                continue  # Skip if logging is paused or stopped

                            # Process temperature line
                            newData = json.loads(line[2:])
                            # Copy/rename keys
                            for key in newData:
                                prevTempJson[renameTempKey(key)] = newData[key]

                            # If we are running Tilt, get current values
                            if (tilt is not None) and (tiltbridge is not None):
                                # Check each of the Tilt colors
                                for color in Tilt.TILT_COLORS:
                                    # Only log the Tilt if the color matches the config
                                    if color == config["tiltColor"]:
                                        tiltValue = tilt.getValue()
                                        if tiltValue is not None:
                                            _temp = tiltValue.temperature
                                            if cc['tempFormat'] == 'C':
                                                _temp = bc.convert(_temp, 'F', 'C')

                                            prevTempJson[color +
                                                         'Temp'] = round(_temp, 2)
                                            prevTempJson[color +
                                                         'SG'] = round(tiltValue.gravity, 3)
                                            prevTempJson[color +
                                                          'Batt'] = round(tiltValue.battery, 3)
                                        else:
                                            prevTempJson[color + 'Temp'] = None
                                            prevTempJson[color + 'SG'] = None
                                            prevTempJson[color + 'Batt'] = None

                            # Expire old BB keypairs
                            if (time.time() - lastBbApi) > timeoutBB:
                                if checkKey(prevTempJson, 'bbbpm'):
                                    del prevTempJson['bbbpm']
                                if checkKey(prevTempJson, 'bbamb'):
                                    del prevTempJson['bbamb']
                                if checkKey(prevTempJson, 'bbves'):
                                    del prevTempJson['bbves']

                            # Expire old iSpindel keypairs
                            if (time.time() - lastiSpindel) > timeoutiSpindel:
                                if checkKey(prevTempJson, 'spinSG'):
                                    prevTempJson['spinSG'] = None
                                if checkKey(prevTempJson, 'spinBatt'):
                                    prevTempJson['spinBatt'] = None
                                if checkKey(prevTempJson, 'spinTemp'):
                                    prevTempJson['spinTemp'] = None

                            # Expire old Tiltbridge values
                            if ((time.time() - lastTiltbridge) > timeoutTiltbridge) and tiltbridge == True:
                                tiltbridge = False # Turn off Tiltbridge in case we switched to BT
                                logMessage("Turned off Tiltbridge.")
                                if checkKey(prevTempJson, color + 'Temp'):
                                    prevTempJson[color + 'Temp'] = None
                                if checkKey(prevTempJson, color + 'SG'):
                                    prevTempJson[color + 'SG'] = None
                                if checkKey(prevTempJson, color + 'Batt'):
                                    prevTempJson[color + 'Batt'] = None

                            # Get newRow
                            newRow = prevTempJson

                            # Log received line if true, false is short message, none = mute
                            if outputJson == True:      # Log full JSON
                                logMessage("Update: " + json.dumps(newRow))
                            elif outputJson == False:   # Log only a notice
                                logMessage('New JSON received from controller.')
                            else:                       # Don't log JSON messages
                                pass

                            # Add row to JSON file
                            # Handle if we are running Tilt or iSpindel
                            if checkKey(config, 'tiltColor'):
                                brewpiJson.addRow(
                                    localJsonFileName, newRow, config['tiltColor'], None)
                            elif checkKey(config, 'iSpindel'):
                                brewpiJson.addRow(
                                    localJsonFileName, newRow, None, config['iSpindel'])
                            else:
                                brewpiJson.addRow(
                                    localJsonFileName, newRow, None, None)

                            # Copy to www dir. Do not write directly to www dir to
                            # prevent blocking www file.
                            shutil.copyfile(localJsonFileName, wwwJsonFileName)

                            # Check if CSV file exists, if not do a header
                            if not os.path.exists(localCsvFileName):
                                csvFile = open(localCsvFileName, "a")
                                delim = ','
                                sepSemaphore = "SEP=" + delim + '\r\n'
                                lineToWrite = sepSemaphore # Has to be first line
                                try:
                                    lineToWrite += ('Timestamp' + delim +
                                                   'Beer Temp' + delim +
                                                   'Beer Set' + delim +
                                                   'Beer Annot' + delim +
                                                   'Chamber Temp' + delim +
                                                   'Chamber Set' + delim +
                                                   'Chamber Annot' + delim +
                                                   'Room Temp' + delim +
                                                   'State')

                                    # If we are configured to run a Tilt
                                    if tilt:
                                        # Write out Tilt Temp and SG Values
                                        for color in Tilt.TILT_COLORS:
                                            # Only log the Tilt if the color is correct according to config
                                            if color == config["tiltColor"]:
                                                if prevTempJson.get(color + 'Temp') is not None:
                                                    lineToWrite += (delim +
                                                                    color + 'Tilt SG')

                                    # If we are configured to run an iSpindel
                                    if ispindel:
                                        lineToWrite += (delim + 'iSpindel SG')

                                    lineToWrite += '\r\n'
                                    csvFile.write
                                    csvFile.write(lineToWrite)
                                    csvFile.close()

                                except IOError as e:
                                    logMessage(
                                        "Unknown error: %s" % str(e))

                            # Now write data to csv file as well
                            csvFile = open(localCsvFileName, "a")
                            delim = ','
                            try:
                                lineToWrite = (time.strftime("%Y-%m-%d %H:%M:%S") + delim +
                                               json.dumps(newRow['BeerTemp']) + delim +
                                               json.dumps(newRow['BeerSet']) + delim +
                                               json.dumps(newRow['BeerAnn']) + delim +
                                               json.dumps(newRow['FridgeTemp']) + delim +
                                               json.dumps(newRow['FridgeSet']) + delim +
                                               json.dumps(newRow['FridgeAnn']) + delim +
                                               json.dumps(newRow['RoomTemp']) + delim +
                                               json.dumps(newRow['State']))

                                # If we are configured to run a Tilt
                                if tilt:
                                    # Write out Tilt Temp and SG Values
                                    for color in Tilt.TILT_COLORS:
                                        # Only log the Tilt if the color is correct according to config
                                        if color == config["tiltColor"]:
                                            if prevTempJson.get(color + 'SG') is not None:
                                                lineToWrite += (delim + json.dumps(
                                                    prevTempJson[color + 'SG']))

                                # If we are configured to run an iSpindel
                                if ispindel:
                                    lineToWrite += (delim +
                                                    json.dumps(newRow['spinSG']))

                                lineToWrite += '\r\n'
                                csvFile.write(lineToWrite)
                            except KeyError as e:
                                logMessage(
                                    "KeyError in line from controller: %s" % str(e))

                            csvFile.close()
                            shutil.copyfile(localCsvFileName, wwwCsvFileName)
                        elif line[0] == 'D':  # Debug message received
                            # Should already been filtered out, but print anyway here.
                            logMessage(
                                "Finding a debug message here should not be possible.")
                            logMessage("Line received was: {0}".format(line))
                        elif line[0] == 'L':  # LCD content received
                            prevLcdUpdate = time.time()
                            lcdText = json.loads(line[2:])
                            lcdText[1] = lcdText[1].replace(lcdText[1][18], "&deg;")
                            lcdText[2] = lcdText[2].replace(lcdText[2][18], "&deg;")
                        elif line[0] == 'C':  # Control constants received
                            cc = json.loads(line[2:])
                            # Update the json with the right temp format for the web page
                            if 'tempFormat' in cc:
                                changeWwwSetting('tempFormat', cc['tempFormat'])
                        elif line[0] == 'S':  # Control settings received
                            prevSettingsUpdate = time.time()
                            cs = json.loads(line[2:])
                            # Do not print this to the log file. This is requested continuously.
                        elif line[0] == 'V':  # Control variables received
                            cv = json.loads(line[2:])
                        elif line[0] == 'N':  # Version number received
                            # Do nothing, just ignore
                            pass
                        elif line[0] == 'h':  # Available devices received
                            deviceList['available'] = json.loads(line[2:])
                            oldListState = deviceList['listState']
                            deviceList['listState'] = oldListState.strip('h') + "h"
                            logMessage("Available devices received: " +
                                       json.dumps(deviceList['available']))
                        elif line[0] == 'd':  # Installed devices received
                            deviceList['installed'] = json.loads(line[2:])
                            oldListState = deviceList['listState']
                            deviceList['listState'] = oldListState.strip('d') + "d"
                            logMessage("Installed devices received: " +
                                       json.dumps(deviceList['installed']))
                        elif line[0] == 'U':  # Device update received
                            logMessage("Device updated to: " + line[2:])
                        else:  # Unknown message received
                            logMessage(
                                "Cannot process line from controller: " + line)
                        # End of processing a line
                    except json.decoder.JSONDecodeError as e:
                        logMessage("JSON decode error: %s" % str(e))
                        logMessage("Line received was: " + line)

                if message is not None:  # Other (debug?) message received
                    try:
                        pass  # I don't think we need to log this
                        # expandedMessage = expandLogMessage.expandLogMessage(message)
                        # logMessage("Controller debug message: " + expandedMessage)
                    except Exception as e:
                        # Catch all exceptions, because out of date file could
                        # cause errors
                        logMessage(
                            "Error while expanding log message: '" + message + "'" + str(e))

            if cs['mode'] == 'p':  # Check for update from temperature profile
                newTemp = temperatureProfile.getNewTemp(util.scriptPath())
                if newTemp != cs['beerSet']:
                    cs['beerSet'] = newTemp
                    # If temperature has to be updated send settings to controller
                    bg_ser.write("j{beerSet:" + json.dumps(cs['beerSet']) + "}")

        except socket.error as e:
            logMessage("Socket error(%d): %s" % (e.errno, e.strerror))
            traceback.print_exc()

except KeyboardInterrupt:
    logMessage("Detected keyboard interrupt, exiting.")
    run = 0 # This should let the loop exit gracefully

except Exception as e:
    logMessage("Caught an unhandled exception, exiting.")
    run = 0 # This should let the loop exit gracefully

# Process a graceful shutdown:

try: bg_ser
except NameError: bg_ser = None
if bg_ser is not None:  # If we are running background serial, stop it
    logMessage("Stopping background serial processing.")
    bg_ser.stop()

try: tilt
except NameError: tilt = None
if tilt is not None:  # If we are running a Tilt, stop it
    logMessage("Stopping Tilt.")
    tilt.stop()

try: thread
except NameError: thread = None
if thread is not None:  # Allow any spawned threads to quit
    for thread in threads:
        logMessage("Waiting for threads to finish.")
        _thread.join()

try: ser
except NameError: ser = None
if ser is not None:  # If we opened a serial port, close it
    if ser.isOpen():
        logMessage("Closing port.")
        ser.close()  # Close port

try: conn
except NameError: conn = None
if conn is not None:  # Close any open socket
    logMessage("Closing open sockets.")
    conn.shutdown(socket.SHUT_RDWR)  # Close socket
    conn.close()

logMessage("Exiting.")
sys.exit(0)  # Exit script
