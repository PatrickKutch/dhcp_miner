#!/usr/bin/env python
##############################################################################
#  Copyright (c) 2024 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
##############################################################################
#    File Abstract:
#    Reads and processes ISC DHCPD log file
#    REQURES https://github.com/MartijnBraam/python-isc-dhcp-leases
#
#    NOTE: mostly reference for Maestro team
##############################################################################

# Author: Patrick Kutch

from __future__ import print_function
from isc_dhcp_leases import IscDhcpLeases
import argparse
import errno
import os.path
from datetime import datetime, timezone
import time
import sys


class LeaseObject(object):
    """
        Place holder for data we want
    """
    pass


def getLeases(inputFile: str) -> dict:
    """
        Reads DHCP leases from the ISC dhdpd lease file

        Return: dict of laest lease informaition

        :raises FileNotFoundError
    """
    if not os.path.isfile(inputFile):
        print("Input file not found")
        raise FileNotFoundError(errno.ENOENT,
                                os.strerror(errno.ENOENT), inputFile)

    leases = IscDhcpLeases(inputFile, False)  # is not a gzip file
    all_leases = leases.get()
    from pprint import pprint as pprint
    foo={}
    minDate = datetime(2023, 1, 1)
    for lease in all_leases:
        leaseTime = datetime(lease.end.year,lease.end.month,lease.end.day)
        if leaseTime > minDate:
            foo[lease.ethernet] = lease

    x = len(foo)


    currentLeases = leases.get_current()
    retMap = {}

    # create own dictory of leases, with less info
    # do not need all of the possible info
    for macAddr in currentLeases:
        lease = currentLeases[macAddr]
        leaseObject = LeaseObject()  # our own blank object we can add to

        leaseObject.ip = lease.ip
        leaseObject.binding_state = lease.binding_state
        leaseObject.start = lease.start

        retMap[macAddr] = leaseObject

    return retMap


def displayLeases(leaseMap: dict, isDelta: bool):
    """
        prints the current DHCP information
    """
    now = datetime.now(timezone.utc)

    if isDelta:
        print(f'There are {len(leaseMap)} updated/new DHCP leases')

    else:
        print(f'There are {len(leaseMap)} DHCP leases')

    for macAddr in leaseMap:
        lease = leaseMap[macAddr]

        leaseAge = now - lease.start
        print(f'{macAddr} {lease.ip} {lease.binding_state} {leaseAge}')

    print()


def sendToService(leaseMap: dict, isDelta: bool):
    """
        Sends the lease information to a remote service

        NOTE: Not IMPLEMENTED YET - up to you guys
        Would expect to get uService ip,port security from
        environment variable or perhaps additional cmdline params
    """
    print("sentToService is not yet implemented")


def monitorLeases(leaseFile: str, interval: float, fnHandleUpdates,
                  alwaysSendAllData: bool = False):
    """
        read the lease file and sends results to the desired location

    """
    previousLeases = {}
    while True:
        dhcpLeases = getLeases(leaseFile)
        if len(previousLeases) == 0 or alwaysSendAllData:
            fnHandleUpdates(dhcpLeases, False)

            if interval < 1:
                return  # not running 'forever', so return

            previousLeases = dhcpLeases

        else:
            # otherwise, running in a loop, so check for updates
            updatedNewLeases = {}
            if not alwaysSendAllData:
                if len(dhcpLeases) > 0:
                    for macAddr in dhcpLeases:
                        lease = dhcpLeases[macAddr]
                        if macAddr not in previousLeases or lease.start != previousLeases[macAddr].start:
                            updatedNewLeases[macAddr] = lease
                            previousLeases[macAddr] = updatedNewLeases[macAddr]

                if len(updatedNewLeases) > 0:
                    fnHandleUpdates(updatedNewLeases, True)  # only send updates

            else:
                fnHandleUpdates(dhcpLeases, False)

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description='ISC DHCPD datfile parser')
    parser.add_argument("-f", "--file", help="the dhcpd lease file with path.",
                        type=str, required=True)
    parser.add_argument("-i", "--interval",
                        help="frequency to check for updates(in secs), default=0 (never)",
                        type=float, default=0.0)
    parser.add_argument("-o", "--output",
                        help='''What to do with the lease information.  Options are:
                                displayLeases  - prints to the screen the results [default]
                                sendToService  - sends the info to another service
                            ''',
                        type=str, default="displayLeases")

    args = parser.parse_args()

    # did they specify a valid way to handle the collected data
    if args.output not in dir(sys.modules[__name__]):
        print(f"ERROR: Invlid output option {args.output}")
        print()
        sys.exit(-1)

    handlerFn = getattr(sys.modules[__name__], args.output)

    monitorLeases(args.file, args.interval, handlerFn)


if __name__ == "__main__":
    main()
    sys.exit(0)
