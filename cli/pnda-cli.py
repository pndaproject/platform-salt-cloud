#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#   Copyright (c) 2016 Cisco and/or its affiliates.
#   This software is licensed to you under the terms of the Apache License, Version 2.0
#   (the "License").
#   You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#   The code, technical concepts, and all information contained herein, are the property of
#   Cisco Technology, Inc.and/or its affiliated entities, under various laws including copyright,
#   international treaties, patent, and/or contract.
#   Any use of the material herein must be in accordance with the terms of the License.
#   All rights not expressly granted by the License are reserved.
#   Unless required by applicable law or agreed to separately in writing, software distributed
#   under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
#   ANY KIND, either express or implied.
#
#   Purpose: Script to create PNDA using Salt-Cloud

import argparse
from argparse import RawTextHelpFormatter
import re
import subprocess
import sys
import shutil
import os
import json
import datetime
import atexit

name_regex = "^[\.a-zA-Z0-9-]+$"
validation_rules = None
start = datetime.datetime.now()

def banner():
    print "🐼  🐼  🐼  🐼  🐼  🐼  🐼  🐼"
    print "     P N D A - C L I"
    print "🐼  🐼  🐼  🐼  🐼  🐼  🐼  🐼"

def run_cmd(cmd):
    print cmd
    os.spawnvpe(os.P_WAIT, cmd[0], cmd, os.environ)

@atexit.register
def display_elasped():
    blue = '\033[94m'
    reset = '\033[0m'
    elapsed = datetime.datetime.now() - start
    print "{}Total execution time: {}{}".format(blue, str(elapsed), reset)

def check_pnda_cluster_available(pnda_cluster):
    try:
        print 'Checking this pnda_cluster does not already exist...'
        out = subprocess.check_output(['sudo','salt','*','grains.get','pnda_cluster'])

        pnda_clusters = {}
        for line in out.splitlines():
            if not line.endswith(':') and not 'Minion did not return' in line:
                pnda_clusters[line.strip()] = True

        if pnda_cluster in pnda_clusters:
            print 'pnda_cluster %s already exists. These pnda_clusters found:' % pnda_cluster
            print pnda_clusters
            sys.exit(1)
    except:
        print 'Error checking whether pnda_cluster exists, carrying on anyway'

def sub_map_file(filepath, inserts):
    print 'Updating %s with %s' % (filepath, inserts)
    newpath = '%s.new' % filepath
    with open (filepath, 'r') as f, open(newpath, 'w') as n:
        for line in f:
            newline = line
            for key, value in inserts.iteritems():
                if '%s = ' % key in line:
                    newline = '{%% set %s = %s %%}\n' % (key, value)
            n.write(newline)
    os.remove(filepath)
    os.rename(newpath,filepath)

def get_cluster_from_map(hadoop_map):
    with open ('map/%s' % hadoop_map, "r") as f:
        data=f.read()
        match = re.search('pnda_cluster = \'(.*?)\'', data)
        pnda_cluster = match.groups()[0]
    return pnda_cluster

def run_salt_cmds(cmds, branch):
    if branch:
        for cmd in cmds:
            cmd.append('saltenv=%s' % branch)
    for cmd in cmds:
        run_cmd(cmd)

def expand_from_maps(hadoop_map, databus_map, new_total_datanodes, new_total_kafkanodes, force, branch):

    pnda_cluster = get_cluster_from_map(hadoop_map)

    salt_cmds = [
     ['sudo','salt','-v', '--state-output=mixed', '-C', "G@pnda_cluster:%s" % pnda_cluster,'state.highstate']
    ]

    if new_total_datanodes is not None:
        sub_map_file('map/%s' %hadoop_map, {'datanodes_number':new_total_datanodes})
        expand_hadoop_cmd = ['sudo','salt-cloud','-m','map/%s' %hadoop_map,'-P']
        if force:
            expand_hadoop_cmd.append('-y')
        run_cmd(expand_hadoop_cmd)
        salt_cmds.append(['sudo','CLUSTER=%s' % pnda_cluster,'salt-run', 'state.orchestrate', "orchestrate.pnda-expand"])

    if new_total_kafkanodes is not None:
        sub_map_file('map/%s' %databus_map, {'brokers_number':new_total_kafkanodes})
        expand_databus_cmd = ['sudo','salt-cloud','-m','map/%s' %databus_map,'-P']
        if force:
            expand_databus_cmd.append('-y')
        run_cmd(expand_databus_cmd)

    run_salt_cmds(salt_cmds, branch)


def create_from_maps(hadoop_map, databus_map, force, branch):
    pnda_cluster = get_cluster_from_map(hadoop_map)
    check_pnda_cluster_available(pnda_cluster)

    create_hadoop_cmd = ['sudo','salt-cloud','-m','map/%s' %hadoop_map,'-P']
    create_databus_cmd = ['sudo','salt-cloud','-m','map/%s' %databus_map,'-P']
    if force:
        create_databus_cmd.append('-y')
        create_hadoop_cmd.append('-y')

    run_cmd(create_databus_cmd)
    run_cmd(create_hadoop_cmd)

    cmds = [
     ['sudo','salt','-v', '--state-output=mixed', '-C', "G@pnda_cluster:%s" % pnda_cluster,'state.highstate'],
     ['sudo','CLUSTER=%s' % pnda_cluster,'salt-run', 'state.orchestrate', "orchestrate.pnda"]
    ]
    run_salt_cmds(cmds, branch)

def destroy_from_maps(hadoop_map, databus_map, force):
    destroy_hadoop_cmd = ['sudo','salt-cloud','-m','map/%s' % databus_map,'-d', '-P']
    destroy_databus_cmd = ['sudo','salt-cloud','-m','map/%s' % hadoop_map,'-d', '-P']
    if force:
        destroy_hadoop_cmd.append('-y')
        destroy_databus_cmd.append('-y')

    run_cmd(destroy_hadoop_cmd)
    run_cmd(destroy_databus_cmd)

def name_string(v):
    try:
        return re.match(name_regex, v).group(0)
    except:
        raise argparse.ArgumentTypeError("String '%s' may contain only  a-z 0-9 and '-'"%v)

def get_validation(param_name):
    return validation_rules[param_name]

def check_validation(restriction, v):
    if restriction.startswith("<="):
        return v <= int(restriction[2:])

    if restriction.startswith(">="):
        return v > int(restriction[2:])

    if restriction.startswith("<"):
        return v < int(restriction[1:])

    if restriction.startswith(">"):
        return v > int(restriction[1:])

    if "-" in restriction:
        restrict_min = int(restriction.split('-')[0])
        restrict_max = int(restriction.split('-')[1])
        return v >= restrict_min and v <= restrict_max

    return v == int(restriction)

def validate_size(param_name, v):
    restrictions = get_validation(param_name)
    for restriction in restrictions.split(','):
        if check_validation(restriction, v):
            return True
    return False

def node_limit(param_name, v):
    as_num = None
    try:
        as_num = int(v)
    except:
        raise argparse.ArgumentTypeError("'%s' must be an integer, %s found"%(param_name,v))

    if not validate_size(param_name, as_num):
        raise argparse.ArgumentTypeError("'%s' is not in valid range %s"%(as_num,get_validation(param_name)) )

    return as_num

def get_args():
    epilog = """examples:
  - create new cluster, prompting for values:
    pnda-cli.py create
  - create a new cluster from existing map file:
    pnda-cli.py create-from-map -e squirrel-land
  - destroy existing cluster:
    pnda-cli.py destroy-from-map -e squirrel-land
  - create cluster without user input:
    pnda-cli.py create -e squirrel-land -f standard -n 5 -o 1 -k 2 -z 3 -y
  - expand cluster based on existing map file:
    pnda-cli.py expand-from-map -e squirrel-land -n 5"""
    parser = argparse.ArgumentParser(formatter_class=RawTextHelpFormatter, description='PNDA CLI', epilog=epilog)
    banner()

    parser.add_argument('command', help='Mode of operation', choices=['create', 'create-from-map', 'destroy-from-map', 'expand-from-map'])
    parser.add_argument('-y', action='store_true', help='Do not prompt for confirmation before creating or destroying VMs')
    parser.add_argument('-e','--pnda-cluster', type=name_string, help='Namespaced environment for machines in this cluster')
    parser.add_argument('-n','--datanodes', type=int, help='How many datanodes for the hadoop cluster')
    parser.add_argument('-o','--opentsdb-nodes', type=int, help='How many Open TSDB nodes for the hadoop cluster')
    parser.add_argument('-k','--kafka-nodes', type=int, help='How many kafka nodes for the databus cluster')
    parser.add_argument('-z','--zk-nodes', type=int, help='How many zookeeper nodes for the databus cluster')
    parser.add_argument('-f','--flavour', help='PNDA flavour: "standard"', choices=['standard'])
    parser.add_argument('-b','--branch', help='Git branch to use (defaults to master)')

    args = parser.parse_args()
    return args

def main():
    args = get_args()
    pnda_cluster = args.pnda_cluster
    datanodes = args.datanodes
    tsdbnodes = args.opentsdb_nodes
    kafkanodes = args.kafka_nodes
    zknodes = args.zk_nodes
    flavour = args.flavour
    force = args.y
    branch = args.branch

    if branch is None:
        branch = 'base'

    if not os.getcwd().endswith('salt-cloud/cli'):
        print 'PNDA CLI must be run from a salt-cloud clone on a saltmaster'
        sys.exit(1)

    os.chdir('../')

    if args.command == 'destroy-from-map':
        if pnda_cluster is not None:
            hadoop = '%s-hadoop.map' % pnda_cluster
            databus = '%s-databus.map' % pnda_cluster
            destroy_from_maps(hadoop, databus, force)
            sys.exit(0)
        else:
            print 'destroy-from-map command must specify pnda_cluster, e.g.\npnda-cli.py destroy-from-map -e squirrel-land'
            sys.exit(1)

    if args.command == 'create-from-map':
        if pnda_cluster is not None:
            hadoop = '%s-hadoop.map' % pnda_cluster
            databus = '%s-databus.map' % pnda_cluster
            create_from_maps(hadoop, databus, force, branch)
            sys.exit(0)
        else:
            print 'create-from-map command must specify pnda_cluster, e.g.\npnda-cli.py create-from-map -e squirrel-land'
            sys.exit(1)

    if args.command == 'expand-from-map':
        if pnda_cluster is not None:
            hadoop = '%s-hadoop.map' % pnda_cluster
            databus = '%s-databus.map' % pnda_cluster
            expand_from_maps(hadoop, databus, datanodes, kafkanodes, force, branch)
            sys.exit(0)
        else:
            print 'expand-from-map command must specify pnda_cluster, e.g.\npnda-cli.py expand-from-map -e squirrel-land -n 5'
            sys.exit(1)

    while pnda_cluster is None:
        pnda_cluster = raw_input("Enter a name for the pnda cluster (e.g. squirrel-land): ")
        if not re.match(name_regex, pnda_cluster):
            print "pnda cluster name may contain only  a-z 0-9 and '-'"
            pnda_cluster = None

    hadoop = '%s-hadoop.map' % pnda_cluster
    databus = '%s-databus.map' % pnda_cluster

    while flavour is None:
        flavour = raw_input("Enter a flavour (standard): ")
        if not re.match("^(standard)$", flavour):
            print "Not a valid flavour"
            flavour = None

    global validation_rules
    validation_file = file('map/templates/%s/validation.json' % flavour)
    validation_rules = json.load(validation_file)
    validation_file.close()

    while datanodes is None:
        datanodes = raw_input("Enter how many Hadoop data nodes (%s): " % get_validation("datanodes"))
        try:
            datanodes = int(datanodes)
        except:
            print "Not a number"
            datanodes = None

        if not validate_size("datanodes", datanodes):
            print "Consider choice again, limits are: %s" % get_validation("datanodes")
            datanodes = None

    while tsdbnodes is None:
        tsdbnodes = raw_input("Enter how many Open TSDB nodes (%s): " % get_validation("opentsdb-nodes"))
        try:
            tsdbnodes = int(tsdbnodes)
        except:
            print "Not a number"
            tsdbnodes = None

        if not validate_size("opentsdb-nodes", tsdbnodes):
            print "Consider choice again, limits are: %s" % get_validation("opentsdb-nodes")
            tsdbnodes = None

    while kafkanodes is None:
        kafkanodes = raw_input("Enter how many Kafka nodes (%s): " % get_validation("kafka-nodes"))
        try:
            kafkanodes = int(kafkanodes)
        except:
            print "Not a number"
            kafkanodes = None

        if not validate_size("kafka-nodes", kafkanodes):
            print "Consider choice again, limits are: %s" % get_validation("kafka-nodes")
            kafkanodes = None

    while zknodes is None:
        zknodes = raw_input("Enter how many Zookeeper nodes (%s): " % get_validation("zk-nodes"))
        try:
            zknodes = int(zknodes)
        except:
            print "Not a number"
            zknodes = None

        if not validate_size("zk-nodes", zknodes):
            print "Consider choice again, limits are: %s" % get_validation("zk-nodes")
            zknodes = None

    node_limit("datanodes", datanodes)
    node_limit("opentsdb-nodes", tsdbnodes)
    node_limit("kafka-nodes", kafkanodes)
    node_limit("zk-nodes", zknodes)

    print 'Copying templates from map/templates/%s' % flavour
    shutil.copy('map/templates/%s/cloudera-cluster.map' % flavour, 'map/%s' % hadoop)
    shutil.copy('map/templates/%s/databus-template.map' % flavour, 'map/%s' % databus)

    sub_map_file('map/%s' % hadoop, {'pnda_cluster':"'%s'"%pnda_cluster, 'cluster_flavour':"'%s'"%flavour, 'datanodes_number':datanodes, 'opentsdb_number':tsdbnodes})
    sub_map_file('map/%s' % databus, {'pnda_cluster':"'%s'"%pnda_cluster, 'brokers_number':kafkanodes, 'zookeepers_number':zknodes})

    create_from_maps('%s' %hadoop, '%s' % databus, force, branch)
    console_info = subprocess.check_output(['sudo','salt', "%s-cdh-edge" % pnda_cluster, 'pnda.ip_addresses', 'console_frontend'])
    print 'Use the PNDA console to get started: http://%s' % console_info.splitlines()[1].replace('    - ', '')
if __name__ == "__main__":
    main()
