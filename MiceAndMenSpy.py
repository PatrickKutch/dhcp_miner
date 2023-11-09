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
#    For a group of networks (listed in a JSON file), this app will go get
#    DHCP reservations for that network from DDI (Mice and Men) using REST API
#    and then generate a report on how many unique MAC addresses are found
#    it will also try to classify the MAC addresses as belonging to VMs, PDU, etc.
#
#    The application will create local cache files so that parsing the data again
#    is much faster.  This was done to speed up development - as it takes a full 
#    hour to gather all of the information via REST API from DDI without the cache.    
#
#    NOTE: mostly reference for Maestro team
##############################################################################

# Author: Patrick Kutch

from __future__ import print_function
import requests
from pprint import pprint as pprint
import os
import sys
from requests.auth import HTTPBasicAuth
from datetime import datetime
from dateutil.relativedelta import relativedelta
import json
import urllib3
import argparse
urllib3.disable_warnings()

# global vairables
OUI_MAP = {}  # read from file in main()
ddiURL = "https://ipam.intel.com/mmws/api/"
authObj = HTTPBasicAuth('notRealUser', 'NotRealPassword')

# default files - can be overridden by command line parameers
__defaultNetworkFile = "NetworkList.json"   # contains the networks to go get data for
__defaultCacheFile = "cache.json"
__defaultOuiFile = "oui.json"


def get(api, **params):
    """
        Reads a request from the REST API.  Just a wrapper.
    """
    global authObj
    if len(params) == 0:
        paramList = ""
    else:
        paramList = None
        for param, value in params.items():
            if None == paramList:
                paramList = "?"
            else:
                paramList += "&"

            paramList += f"{param}={value}"

    headers = {'content-type': 'application/json'}
    print(ddiURL + api + paramList)  # just for debugging, can remove
    return requests.get(ddiURL + api + paramList, auth=authObj, verify=False, headers = headers)


def getAndShow(api, **params):
    """
        Dev/Debug routine wrapper for calling REST API.  Prints all the info.    
    """
    response = get(api, **params)
    if response.ok:
        respData = response.json()
        pprint(respData)
        return respData['result']
    else:
        print(f"Error: {response.reason}")
        pprint(response.content)


def getResponseData(api, **params):
    """
        Wrapper to sent a REST API call, it will check for valid response
        and send it back, else exit program
    """
    response = get(api, **params)
    if response.ok:
        respData = response.json()
        return respData['result']
    else:
        print(f"Error: {response.reason}")
        pprint(response.content)
        sys.exit()


def readMapFromJsonFile(fName):
    '''
        Reads a dictionary from a json file.
    '''
    try:
        with open(fName, "rt") as fp:
            return json.load(fp)

    except Exception:
        print(f"{fName} was invlid or empty.")
        return {}


def writeMapFromJsonFile(fName, dict):
    '''
        writes a dictionary (hash table) to a json file
    '''
    with open(fName, "wt") as fp:
        json.dump(dict, fp, indent=2)


def getInfoBlockForNetwork(networkSubnet, cacheFile, useLocalReservationCache=False):
    '''
        Real work is done in this routine.
        Given the passed network subnet (e.g. "10.102.22.0/23") the rounine
        will contact DDI and get info about that subnet (Forest is the term DDI uses I think)
        and then make a call to get all DHCP reservations on that subnet.  I think there must
        be a more efficient way of doing this, as this is pretty slow.

        Once the data is gathered, it keeps track of all the unique MAC addresses found and tries
        to classify them as being from a VM, PDU, Raritan etc. 

        I do not keep track of the IP addresses in this app, but one could easily add that for
        other Maestro purposes.
    '''
    retMap = {}
    retMap['Other'] = {}
    retMap['All'] = {}
    checkDate = datetime.now() - relativedelta(months=12) # only get stuff in this time period

    print(f'Gathering Info for network: {networkSubnet}')
    inpFormat = '%b %d, %Y %H:%M:%S'

    RangeDict = readMapFromJsonFile(cacheFile)

    if networkSubnet not in RangeDict:  # not in cache, so go read it via REST API
        rangeData = getResponseData('Ranges', filter=f'name={networkSubnet}') # Just gets the info block for the network
        RangeDict[networkSubnet] = rangeData

        if useLocalReservationCache:
            writeMapFromJsonFile(cacheFile, RangeDict)

    else:
        rangeData = RangeDict[networkSubnet]

    try:
        rangeRef = rangeData['ranges'][0]['ref']

    except Exception:
        return retMap

    fName = networkSubnet.replace('/','_')
    if useLocalReservationCache:
        respData = readMapFromJsonFile(fName + ".json")
    else:
        respData = None

    if not respData:
        # did not read it from a local cache file (the subnet name.json file)
        # so call rest API to go get all IP addresses in that range
        respData = getResponseData(f'{rangeRef}/IPAMRecords')  # gets the IP range
        if useLocalReservationCache:
            writeMapFromJsonFile(fName + ".json", respData)

    # respData is an array of all DHCP records for the network
    for record in respData['ipamRecords']:
        if len(record['lastKnownClientIdentifier']) > 0 : # IP as an associate MAC address at some point
            lastSeen = datetime.strptime(record['lastSeenDate'], inpFormat)

            # probably lazy way of doing this - see Note below
            if lastSeen > checkDate:  # only care if it is within a certain time
                # NOTE: this is probably a very inefficeint way of doing this, there probably is a API parameters
                # to specify a date range - worth investigating
                macAddr = record['lastKnownClientIdentifier']
                # try and figure out if it is a VM, switch, KVM, etc. - not an efficeint way of doing it, but works
                foundMatch = False
                for ouiType in OUI_MAP:
                    if ouiType not in retMap:
                        retMap[ouiType] = {}

                    if not foundMatch:
                        for macID in OUI_MAP[ouiType]:
                            if macID.lower() in macAddr[:len(macID)].lower():
                                retMap[ouiType][macAddr] = record
                                foundMatch = True

                if not foundMatch:  # unknown OUI vendor, so put in 'other'
                    retMap['Other'][macAddr] = record

                # store also in 'All'
                retMap['All'][macAddr] = record

            else:
                #print(f'{checkDate} {lastSeen}')
                pass

    return retMap


def CreateCsvFiles(blockMap):
    '''
        For a subnet (and Lab), dumps all of the MAC addresses.
        Each line is in the format of subnet, MAC1,MAC2,MAC3,etc.
    '''
    labMap = {}
    for lab in blockMap:
        subnetMap = {}
        labMacs = {}
        subnetMap['Duplicates'] = {}

        for subnet in blockMap[lab]:
            for type in blockMap[lab][subnet]:
                if type not in subnetMap:
                    subnetMap[type] = {}

                for macAddr in blockMap[lab][subnet][type]:
                    if subnet not in subnetMap[type]:
                        subnetMap[type][subnet] = [subnet,]

                    subnetMap[type][subnet].append(macAddr)

                    if macAddr in labMacs:
                        labMacs[macAddr].append(subnet)
                        subnetMap['Duplicates'][macAddr] = labMacs[macAddr]

                    else:
                        labMacs[macAddr] = []
                        labMacs[macAddr].append(subnet)

        labMap[lab] = subnetMap

        for type in subnetMap:
            key = f"DHCP_{lab}_{type}"
            if len(subnetMap[type]) > 0:
                with open(f"{key}.csv", "wt") as fp:
                    for subnet in subnetMap[type]:
                        line = ",".join(subnetMap[type][subnet])
                        fp.write(line)
                        fp.write('\n')
    return labMap


def main():
    global OUI_MAP

    parser = argparse.ArgumentParser(description='Mice and Men DHCP Miner')
    # JSON file listing all the subnets to go mine data for
    parser.add_argument("-n", "--networks", help=f'json file listing the lab and subnets to get data for. Default={__defaultNetworkFile}',
                        type=str, default=__defaultNetworkFile)

    # a cache file for the info block for each subnet.  The way I made this, it goes and gathers info on each network (Forest - I think)
    # and then gets the details (all the IP addresses) in each network.  If the networks do not change, we can cache the
    # first part, saving time.  With this cache file, it takes about 1/2 as long to gather all of the data
    parser.add_argument("-c", "--cache", help=f'cache file for the DHCP Forests. Default={__defaultCacheFile}',
                        type=str, default=__defaultCacheFile)

    # the 1st 3 parts of a MAC are IANA numbers, that can help identify the company (such as Raritan, Cisco, etc.) owns that
    # MAC.  This helps to know if the MAC is a VM, a switch, a PDU etc
    parser.add_argument("-o", "--oui", help=f'oui file - contains MAC OUI for identification.  Default={__defaultOuiFile}',
                        type=str, default=__defaultOuiFile)

    args = parser.parse_args()

    # Note: - I do not validate these parameters, it should be done :-)
    # oui and cache are not vital, but networks is required

    userNameFromEnv = os.getenv("ddi_username")
    passwordFromEnv = os.getenv("ddi_password")

    if userNameFromEnv is None or passwordFromEnv is None:
        print("Error: you must set 'ddi_userame' and 'ddi_password' environment variables")
        print("example: set ddi_username=AMR\\pgkutch")
        return

    networks = readMapFromJsonFile(args.networks)
    OUI_MAP = readMapFromJsonFile(args.oui)

    global authObj
    authObj = HTTPBasicAuth(userNameFromEnv, passwordFromEnv)

    blockMap = {}
    count = 0

    for lab, networkList in networks.items():
        for network in networkList:
            # Read info block for subnet, if not in cache, will read via REST API, and add to cache
            # also, last arg is to cache the reservations to local files.  This is for debugging and such
            # as it takes a LONG time to go gather all the data
            reservationBlockInfo = getInfoBlockForNetwork(network, args.cache, True)
            # create a map with
            if lab not in blockMap:
                blockMap[lab] = {}

            blockMap[lab][network] = reservationBlockInfo
            count += len(reservationBlockInfo)

    # I have all the data, now go dump to files for Frank and team
    # also creates a nice map for me to print the summary
    retMap = CreateCsvFiles(blockMap)

    # print a summary of # of MAC addresses in each lab, by classification
    for lab, labMap in retMap.items():
        print(f'{lab}')
        for type, subnetList in labMap.items():
            if type == 'Duplicates':
                total = len(subnetList)
            else:
                total = 0
                for subnet in subnetList:
                    total += len(subnetList[subnet])

            if total > 0:
                print(f"\t{type} - {total}")

    print()


if __name__ == "__main__":
    main()
